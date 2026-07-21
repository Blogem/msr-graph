package sandbox_test

// Unit tests for the Pool's lifecycle, timeout, and concurrency behavior
// (openspec/changes/sandbox-exec-pool/specs/sandbox-execution/spec.md,
// tasks 6.1-6.7). These run against fakeRuntime (fake_test.go) and require
// no Docker daemon (design D2, "Pool logic verifiable without a Docker
// daemon"). The real Docker-backed isolation properties are covered by the
// single gated integration test in integration_test.go (6.8).

import (
	"bytes"
	"context"
	"errors"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/blogem/msr-graph/internal/sandbox"
)

// testConfig returns a valid sandbox.Config for unit tests: pool size and
// timeout are the parameters under test, everything else is a sane,
// arbitrary fixed value (the fake runtime ignores the resource-limit
// fields entirely).
func testConfig(poolSize int, timeout time.Duration) sandbox.Config {
	return sandbox.Config{
		PoolSize:    poolSize,
		CPUs:        1,
		MemoryBytes: 256 << 20,
		PidsLimit:   128,
		TmpfsSize:   64 << 20,
		Timeout:     timeout,
		IdleTTL:     time.Hour,
		Image:       "fake-image:test",
		DataHostDir: "/fake/data",
	}
}

// waitFor polls cond every 5ms until it returns true or timeout elapses,
// failing the test if the condition is never met. It exists because pool
// replenishment happens in a background goroutine (design D1/D8): tests
// must wait for it rather than asserting immediately after Run returns.
func waitFor(t *testing.T, timeout time.Duration, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for {
		if cond() {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("condition not met within %s", timeout)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// 6.1 -- drain/replenish: after a Run, the used container is removed and a
// fresh one is created and returned to the pool, restoring N ready
// containers. Assert create/remove call ordering and counts.
func TestPool_DrainAndReplenish(t *testing.T) {
	rt := newFakeRuntime()
	p, err := sandbox.New(context.Background(), testConfig(3, time.Second), rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}
	defer p.Close()

	if got := rt.CreateCount(); got != 3 {
		t.Fatalf("expected 3 initial creates warming the pool, got %d", got)
	}

	usedBefore := append([]string(nil), rt.CreatedIDs()...)

	if _, _, _, err := p.Run(context.Background(), []byte("print('hi')")); err != nil {
		t.Fatalf("Run: %v", err)
	}

	// Replenishment is async: wait for the 4th container to be created and
	// exactly one removal to have happened.
	waitFor(t, time.Second, func() bool { return rt.CreateCount() == 4 })
	waitFor(t, time.Second, func() bool { return rt.RemoveCount() == 1 })

	removed := rt.RemovedIDs()
	if len(removed) != 1 {
		t.Fatalf("expected exactly 1 removed container, got %v", removed)
	}
	if !contains(usedBefore, removed[0]) {
		t.Fatalf("expected the removed container %q to be one of the 3 originally warmed containers %v", removed[0], usedBefore)
	}

	// Ordering: the exec'd container must be removed, and a fresh
	// container created, after the exec completes -- never before. New
	// always calls Reap once before warming (design D9), so we count
	// Create occurrences rather than assume a fixed positional index for
	// the 4th (replenishment) Create.
	calls := rt.Calls()
	execIdx, removeIdx, fourthCreateIdx := -1, -1, -1
	createSeen := 0
	for i, c := range calls {
		switch c.Method {
		case callExec:
			if execIdx == -1 {
				execIdx = i
			}
		case callRemove:
			if removeIdx == -1 {
				removeIdx = i
			}
		case callCreate:
			createSeen++
			if createSeen == 4 && fourthCreateIdx == -1 {
				fourthCreateIdx = i
			}
		}
	}
	if execIdx == -1 || removeIdx == -1 || fourthCreateIdx == -1 {
		t.Fatalf("expected Exec, Remove, and a 4th Create in the call log, got %v", calls)
	}
	if !(execIdx < removeIdx) {
		t.Fatalf("expected Exec (idx %d) before Remove (idx %d): %v", execIdx, removeIdx, calls)
	}
	if !(removeIdx < fourthCreateIdx) {
		t.Fatalf("expected Remove (idx %d) before the replenishment Create (idx %d): %v", removeIdx, fourthCreateIdx, calls)
	}
}

// 6.2 -- single-use invariant: across many runs, no container id is ever
// handed to Exec twice; each Run execs a distinct id. Pool size 1 forces
// every Run to wait for replenishment, exercising the invariant serially.
func TestPool_SingleUseInvariant(t *testing.T) {
	rt := newFakeRuntime()
	p, err := sandbox.New(context.Background(), testConfig(1, time.Second), rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}
	defer p.Close()

	const numRuns = 20
	for i := 0; i < numRuns; i++ {
		if _, _, _, err := p.Run(context.Background(), []byte("print('run')")); err != nil {
			t.Fatalf("Run %d: %v", i, err)
		}
	}

	execed := rt.ExecedIDs()
	if len(execed) != numRuns {
		t.Fatalf("expected %d execs, got %d: %v", numRuns, len(execed), execed)
	}
	seen := make(map[string]bool, len(execed))
	for _, id := range execed {
		if seen[id] {
			t.Fatalf("container %q was exec'd more than once: %v", id, execed)
		}
		seen[id] = true
	}
}

// 6.3 -- timeout: with a short Timeout and a hanging-exec fake, Run returns
// an error satisfying errors.Is(err, sandbox.ErrTimeout), the container is
// force-removed, and this is distinguishable from a normal non-zero exit
// (6.4 asserts the non-zero-exit path returns a nil error; this asserts
// the timeout path returns a non-nil error identifiable as a timeout).
func TestPool_Timeout(t *testing.T) {
	rt := newFakeRuntime()
	rt.setHangExec(true)

	p, err := sandbox.New(context.Background(), testConfig(1, 50*time.Millisecond), rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}
	defer p.Close()

	_, _, _, runErr := p.Run(context.Background(), []byte("while True: pass"))
	if runErr == nil {
		t.Fatal("expected a timeout error, got nil")
	}
	if !errors.Is(runErr, sandbox.ErrTimeout) {
		t.Fatalf("expected errors.Is(err, sandbox.ErrTimeout), got: %v", runErr)
	}

	waitFor(t, time.Second, func() bool { return rt.RemoveCount() >= 1 })
}

// 6.4 -- result capture: stdout is returned verbatim (unparsed); a
// non-zero exit returns the captured stderr + exit code with a nil error.
func TestPool_ResultCapture(t *testing.T) {
	tests := []struct {
		name   string
		result sandbox.ExecResult
	}{
		{
			name:   "success with stdout",
			result: sandbox.ExecResult{Stdout: []byte(`{"count":3}`), ExitCode: 0},
		},
		{
			name:   "non-zero exit reports stderr and code, not an error",
			result: sandbox.ExecResult{Stderr: []byte("Traceback: boom"), ExitCode: 1},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rt := newFakeRuntime()
			rt.setDefaultExec(tt.result, nil)

			p, err := sandbox.New(context.Background(), testConfig(1, time.Second), rt)
			if err != nil {
				t.Fatalf("sandbox.New: %v", err)
			}
			defer p.Close()

			stdout, stderr, exitCode, runErr := p.Run(context.Background(), []byte("print('x')"))
			if runErr != nil {
				t.Fatalf("expected nil infrastructure error, got: %v", runErr)
			}
			if !bytes.Equal(stdout, tt.result.Stdout) {
				t.Errorf("stdout = %q, want %q (verbatim)", stdout, tt.result.Stdout)
			}
			if !bytes.Equal(stderr, tt.result.Stderr) {
				t.Errorf("stderr = %q, want %q", stderr, tt.result.Stderr)
			}
			if exitCode != tt.result.ExitCode {
				t.Errorf("exitCode = %d, want %d", exitCode, tt.result.ExitCode)
			}
		})
	}
}

// 6.5 -- concurrency under -race: more concurrent Run calls than pool size
// N drain and refill the pool with no data race and no double-use;
// callers beyond N block until replenishment provides a container. Run
// this test with `go test -race`.
func TestPool_ConcurrencyRace(t *testing.T) {
	const poolSize = 3
	const numRuns = 15

	rt := newFakeRuntime()
	rt.setExecDelay(10 * time.Millisecond) // widen the overlap window

	p, err := sandbox.New(context.Background(), testConfig(poolSize, 5*time.Second), rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}
	defer p.Close()

	var wg sync.WaitGroup
	errCh := make(chan error, numRuns)
	for i := 0; i < numRuns; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, _, _, runErr := p.Run(context.Background(), []byte("print('concurrent')"))
			errCh <- runErr
		}()
	}
	wg.Wait()
	close(errCh)

	for runErr := range errCh {
		if runErr != nil {
			t.Errorf("unexpected Run error: %v", runErr)
		}
	}

	execed := rt.ExecedIDs()
	if len(execed) != numRuns {
		t.Fatalf("expected %d execs, got %d: %v", numRuns, len(execed), execed)
	}
	seen := make(map[string]bool, len(execed))
	for _, id := range execed {
		if seen[id] {
			t.Fatalf("container %q was exec'd more than once (double-use): %v", id, execed)
		}
		seen[id] = true
	}
}

// 6.6 -- Close force-removes idle containers and stops replenishment: no
// send into the pool and no goroutine leak after Close returns.
func TestPool_Close(t *testing.T) {
	rt := newFakeRuntime()
	p, err := sandbox.New(context.Background(), testConfig(3, time.Second), rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}

	// Let the runtime settle before taking the goroutine baseline so we
	// are not counting transient setup goroutines.
	time.Sleep(20 * time.Millisecond)
	before := runtime.NumGoroutine()

	if err := p.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	waitFor(t, time.Second, func() bool { return rt.RemoveCount() == 3 })

	createsAtClose := rt.CreateCount()

	// Give any (incorrectly) still-running replenishment goroutine a
	// window to misbehave, then assert nothing changed.
	time.Sleep(100 * time.Millisecond)

	if got := rt.CreateCount(); got != createsAtClose {
		t.Errorf("expected no Create calls after Close, went from %d to %d", createsAtClose, got)
	}

	after := runtime.NumGoroutine()
	if after > before {
		t.Errorf("goroutine count grew after Close (leak?): before=%d after=%d", before, after)
	}
}

// 6.7 -- startup sweep: New calls Reap before any Create, so pre-existing
// labelled containers (seeded in the fake, modeling orphans left by a
// crashed prior process) are force-removed before the pool is warmed.
func TestPool_StartupSweep(t *testing.T) {
	rt := newFakeRuntime()
	rt.seedLabelled("orphan-1", "orphan-2")

	p, err := sandbox.New(context.Background(), testConfig(2, time.Second), rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}
	defer p.Close()

	if got := rt.ReapCalls(); got != 1 {
		t.Fatalf("expected exactly 1 Reap call during New, got %d", got)
	}

	calls := rt.Calls()
	reapIdx, firstCreateIdx := -1, -1
	for i, c := range calls {
		if c.Method == callReap && reapIdx == -1 {
			reapIdx = i
		}
		if c.Method == callCreate && firstCreateIdx == -1 {
			firstCreateIdx = i
		}
	}
	if reapIdx == -1 {
		t.Fatalf("expected a Reap call, got none: %v", calls)
	}
	if firstCreateIdx == -1 {
		t.Fatalf("expected at least one Create call, got none: %v", calls)
	}
	if reapIdx > firstCreateIdx {
		t.Fatalf("expected Reap (idx %d) before the first Create (idx %d): %v", reapIdx, firstCreateIdx, calls)
	}

	removed := rt.RemovedIDs()
	for _, orphan := range []string{"orphan-1", "orphan-2"} {
		if !contains(removed, orphan) {
			t.Errorf("expected orphan %q to be removed by the startup sweep, removed=%v", orphan, removed)
		}
	}
}

// TestPool_CloseDuringRun is a regression test for a fixed HIGH-severity
// concurrency bug (design D8, fix F1): a Run racing a concurrent Close could
// have its post-Exec replenishment goroutine slip a freshly created
// container into `ready` *after* Close had already drained and force-removed
// every idle container, permanently orphaning it (leaked, never reachable by
// any future Run, never removed). The fix serializes startReplenish's
// wg.Add/spawn against Close's closed=true + close(done) under the same
// mutex, so every replenishment Close ever needs to account for is either
// already spawned (and guaranteed to finish, via wg.Wait, before Close
// drains ready) or never spawned at all.
//
// This drives many concurrent Run calls against a small pool while Close is
// invoked mid-flight, using artificial Exec/Create delays to widen the race
// window, and asserts that after everything settles, every container the
// fake ever created was eventually removed -- i.e. created == removed, with
// no id created but never removed (the orphan signature of the bug). Must
// pass under `go test -race` and remain stable under `-count=20`.
func TestPool_CloseDuringRun(t *testing.T) {
	const poolSize = 2
	const numRuns = 8

	rt := newFakeRuntime()
	rt.setExecDelay(5 * time.Millisecond)   // widen the window Run spends checked-out
	rt.setCreateDelay(5 * time.Millisecond) // widen the window a replenish is mid-flight

	p, err := sandbox.New(context.Background(), testConfig(poolSize, time.Second), rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}

	var wg sync.WaitGroup
	for i := 0; i < numRuns; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			// Any outcome is acceptable here (a successful run, or an error
			// because the pool closed mid-wait) -- the property under test
			// is "no orphaned container", not "every Run must succeed".
			_, _, _, _ = p.Run(context.Background(), []byte("print('x')"))
		}()
	}

	// Give some Runs a chance to acquire a container and start (or finish)
	// Exec/replenish before Close races in.
	time.Sleep(2 * time.Millisecond)

	closeErr := p.Close()
	if closeErr != nil {
		t.Fatalf("Close returned an unexpected error: %v", closeErr)
	}

	// Close only waits for replenishment goroutines (wg), not for
	// in-flight Run calls, so wait for every Run goroutine to fully finish
	// (including its own Remove of the container it was using) before
	// taking the final created/removed snapshot.
	wg.Wait()

	created := rt.CreatedIDs()
	removed := rt.RemovedIDs()

	if len(created) != len(removed) {
		t.Fatalf("orphaned container(s) detected: %d created but only %d removed\ncreated=%v\nremoved=%v",
			len(created), len(removed), created, removed)
	}
	removedSet := make(map[string]bool, len(removed))
	for _, id := range removed {
		removedSet[id] = true
	}
	for _, id := range created {
		if !removedSet[id] {
			t.Errorf("container %q was created but never removed (orphaned by a Run/Close race)", id)
		}
	}
}

// TestPool_New_ConfigValidation asserts New (fix F6) rejects an invalid
// PoolSize, Timeout, or IdleTTL/Timeout relationship before ever touching
// the Runtime -- a misconfigured pool must fail fast at startup with a
// descriptive error rather than call Reap or Create against a nonsensical
// configuration.
func TestPool_New_ConfigValidation(t *testing.T) {
	base := testConfig(3, time.Second)

	tests := []struct {
		name   string
		mutate func(sandbox.Config) sandbox.Config
	}{
		{
			name:   "PoolSize zero",
			mutate: func(c sandbox.Config) sandbox.Config { c.PoolSize = 0; return c },
		},
		{
			name:   "PoolSize negative",
			mutate: func(c sandbox.Config) sandbox.Config { c.PoolSize = -1; return c },
		},
		{
			name:   "Timeout zero",
			mutate: func(c sandbox.Config) sandbox.Config { c.Timeout = 0; return c },
		},
		{
			name:   "Timeout negative",
			mutate: func(c sandbox.Config) sandbox.Config { c.Timeout = -time.Second; return c },
		},
		{
			name:   "IdleTTL equal to Timeout",
			mutate: func(c sandbox.Config) sandbox.Config { c.IdleTTL = c.Timeout; return c },
		},
		{
			name:   "IdleTTL less than Timeout",
			mutate: func(c sandbox.Config) sandbox.Config { c.IdleTTL = c.Timeout - time.Millisecond; return c },
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rt := newFakeRuntime()
			cfg := tt.mutate(base)

			p, err := sandbox.New(context.Background(), cfg, rt)
			if err == nil {
				t.Fatalf("expected an error for invalid config %+v, got nil (pool=%v)", cfg, p)
			}
			if p != nil {
				t.Fatalf("expected a nil pool on config validation failure, got %v", p)
			}
			if got := rt.ReapCalls(); got != 0 {
				t.Errorf("expected New to reject the config before ever calling Reap, but Reap was called %d times", got)
			}
			if got := rt.CreateCount(); got != 0 {
				t.Errorf("expected New to reject the config before ever calling Create, but Create was called %d times", got)
			}
		})
	}
}

// TestPool_New_ReapError asserts that a failing startup sweep (Reap) fails
// New with a descriptive error mentioning the sweep, and never proceeds to
// warm any containers.
func TestPool_New_ReapError(t *testing.T) {
	rt := newFakeRuntime()
	rt.setReapErr(errors.New("daemon unreachable"))

	p, err := sandbox.New(context.Background(), testConfig(3, time.Second), rt)
	if err == nil {
		t.Fatal("expected New to fail when Reap fails, got nil error")
	}
	if p != nil {
		t.Fatalf("expected a nil pool, got %v", p)
	}
	if !strings.Contains(err.Error(), "sweep") && !strings.Contains(err.Error(), "Reap") {
		t.Errorf("expected the error to mention the startup sweep/Reap, got: %v", err)
	}
	if got := rt.CreateCount(); got != 0 {
		t.Errorf("expected no containers created when Reap fails, got %d", got)
	}
}

// TestPool_New_CreateRollback asserts that when a warm Create fails partway
// through New's initial warm-up loop, New force-removes every container it
// had already created during this call before returning the error (design
// D8): a mid-warm-up failure must never leak partially-warmed containers.
//
// The failure point is induced by racing a background goroutine's
// rt.setCreateErr call against New's sequential warm-up loop rather than
// pinned to an exact call index: the fake's knobs are simple "on/off from
// now" toggles, not scripted per-call-number, so the exact Kth call that
// fails can vary by a call or two depending on scheduling. What must always
// hold, regardless of exactly which call fails, is the invariant under
// test: New fails, and every container created before the failure is rolled
// back.
func TestPool_New_CreateRollback(t *testing.T) {
	const poolSize = 5
	rt := newFakeRuntime()
	rt.setCreateDelay(20 * time.Millisecond) // widen the window to flip the error mid-warm-up

	type result struct {
		pool *sandbox.Pool
		err  error
	}
	resultCh := make(chan result, 1)
	go func() {
		p, err := sandbox.New(context.Background(), testConfig(poolSize, time.Second), rt)
		resultCh <- result{pool: p, err: err}
	}()

	// Wait for at least one container to be warmed, then inject the error
	// so a later Create in the same loop fails.
	waitFor(t, time.Second, func() bool { return rt.CreateCount() >= 1 })
	rt.setCreateErr(errors.New("daemon out of resources"))

	var res result
	select {
	case res = <-resultCh:
	case <-time.After(5 * time.Second):
		t.Fatal("sandbox.New did not return in time")
	}

	if res.err == nil {
		t.Fatal("expected New to return an error when a warm Create fails")
	}
	if res.pool != nil {
		t.Fatalf("expected a nil pool on rollback, got %v", res.pool)
	}

	created := rt.CreatedIDs()
	if len(created) < 1 || len(created) >= poolSize {
		t.Fatalf("expected 1..%d containers created before the failure (not all %d), got %d: %v",
			poolSize-1, poolSize, len(created), created)
	}

	removed := rt.RemovedIDs()
	if len(removed) != len(created) {
		t.Fatalf("expected all %d partially-warmed containers to be rolled back (removed), got %d removed: %v",
			len(created), len(removed), removed)
	}
	for _, id := range created {
		if !contains(removed, id) {
			t.Errorf("expected partially-warmed container %q to be removed during rollback, removed=%v", id, removed)
		}
	}
}

// TestPool_ReplenishBackoff asserts that a persistently-then-transiently
// failing replacement Create is retried with the pool's bounded backoff
// (design D8, replenishInitialBackoff/replenishMaxBackoff in pool.go) rather
// than busy-spinning: the replacement eventually succeeds and restores the
// pool to a ready container, but only after at least one backoff interval
// has elapsed, and with a small, bounded number of attempts.
func TestPool_ReplenishBackoff(t *testing.T) {
	rt := newFakeRuntime()

	p, err := sandbox.New(context.Background(), testConfig(1, time.Second), rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}
	defer p.Close()

	// Set the error BEFORE Run so the replacement Create it triggers
	// deterministically fails on its very first attempt (no race: New's
	// initial warm-up already completed, and Run has not yet been called).
	rt.setCreateErr(errors.New("daemon busy"))

	start := time.Now()
	if _, _, _, err := p.Run(context.Background(), []byte("print('x')")); err != nil {
		t.Fatalf("Run: %v", err)
	}

	// Let the bounded backoff (initial 200ms, doubling) fail at least once
	// before letting the replacement succeed.
	time.Sleep(280 * time.Millisecond)
	rt.setCreateErr(nil)

	waitFor(t, 3*time.Second, func() bool { return rt.CreateCount() == 2 })
	elapsed := time.Since(start)

	if elapsed < 200*time.Millisecond {
		t.Errorf("replacement succeeded too fast (%s); expected the bounded backoff to have delayed at least one retry, not busy-spun", elapsed)
	}
	if elapsed > 3*time.Second {
		t.Errorf("replacement took too long (%s); backoff should be bounded, not stuck", elapsed)
	}
	if got := rt.CreateAttempts(); got < 2 || got > 6 {
		t.Errorf("expected a small, bounded number of Create attempts (retried on backoff, not busy-spun), got %d", got)
	}
}

// TestPool_Close_RemoveError asserts that Close returns the first removal
// error it encounters while force-removing idle containers, rather than
// swallowing it.
func TestPool_Close_RemoveError(t *testing.T) {
	rt := newFakeRuntime()
	p, err := sandbox.New(context.Background(), testConfig(3, time.Second), rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}

	wantErr := errors.New("remove boom")
	rt.setRemoveErr(wantErr)

	closeErr := p.Close()
	if closeErr == nil {
		t.Fatal("expected Close to return the removal error, got nil")
	}
	if !errors.Is(closeErr, wantErr) {
		t.Fatalf("expected Close's error to be (or wrap) %v, got: %v", wantErr, closeErr)
	}
}

// TestPool_CreateSpec asserts that New passes the Runtime a ContainerSpec
// derived exactly from Config: the resource limits and image/data-mount
// fields must match Config verbatim, and Labels must include SandboxLabel
// so the startup sweep (Reap, design D9) can find every sandbox this
// process creates.
func TestPool_CreateSpec(t *testing.T) {
	cfg := sandbox.Config{
		PoolSize:    2,
		CPUs:        2.5,
		MemoryBytes: 512 << 20,
		PidsLimit:   64,
		TmpfsSize:   32 << 20,
		Timeout:     time.Second,
		IdleTTL:     time.Hour,
		Image:       "msr-sandbox-base:test-spec",
		DataHostDir: "/fake/data/spec",
	}

	rt := newFakeRuntime()
	p, err := sandbox.New(context.Background(), cfg, rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}
	defer p.Close()

	specs := rt.CreatedSpecs()
	if len(specs) != cfg.PoolSize {
		t.Fatalf("expected %d created specs, got %d", cfg.PoolSize, len(specs))
	}

	for i, spec := range specs {
		if spec.Image != cfg.Image {
			t.Errorf("spec[%d].Image = %q, want %q", i, spec.Image, cfg.Image)
		}
		if spec.DataHostDir != cfg.DataHostDir {
			t.Errorf("spec[%d].DataHostDir = %q, want %q", i, spec.DataHostDir, cfg.DataHostDir)
		}
		if spec.CPUs != cfg.CPUs {
			t.Errorf("spec[%d].CPUs = %v, want %v", i, spec.CPUs, cfg.CPUs)
		}
		if spec.MemoryBytes != cfg.MemoryBytes {
			t.Errorf("spec[%d].MemoryBytes = %d, want %d", i, spec.MemoryBytes, cfg.MemoryBytes)
		}
		if spec.PidsLimit != cfg.PidsLimit {
			t.Errorf("spec[%d].PidsLimit = %d, want %d", i, spec.PidsLimit, cfg.PidsLimit)
		}
		if spec.TmpfsSize != cfg.TmpfsSize {
			t.Errorf("spec[%d].TmpfsSize = %d, want %d", i, spec.TmpfsSize, cfg.TmpfsSize)
		}
		if spec.IdleTTL != cfg.IdleTTL {
			t.Errorf("spec[%d].IdleTTL = %v, want %v", i, spec.IdleTTL, cfg.IdleTTL)
		}
		if got := spec.Labels[sandbox.SandboxLabel]; got != "1" {
			t.Errorf("spec[%d].Labels[%q] = %q, want \"1\"", i, sandbox.SandboxLabel, got)
		}
	}
}

func contains(ids []string, id string) bool {
	for _, v := range ids {
		if v == id {
			return true
		}
	}
	return false
}

// firstExecID returns the container id of the first Exec call in the log, or
// "" if none occurred.
func firstExecID(calls []callRecord) string {
	for _, c := range calls {
		if c.Method == callExec {
			return c.ID
		}
	}
	return ""
}

// Age-aware acquisition (stale-container "No such container" fix): a warm
// container's PID 1 is `sleep <IdleTTL>` with AutoRemove, so one that has sat
// idle in the pool past its TTL has self-reaped. Run must detect the stale
// container by its expiry, remove it, and create a fresh replacement inline
// so the run still succeeds -- never exec the vanished container.
func TestPool_StaleContainerReplacedBeforeExec(t *testing.T) {
	rt := newFakeRuntime()
	cfg := testConfig(1, 40*time.Millisecond)
	cfg.IdleTTL = 80 * time.Millisecond // must exceed Timeout (New validates)
	p, err := sandbox.New(context.Background(), cfg, rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}
	defer p.Close()

	warmed := rt.CreatedIDs()
	if len(warmed) != 1 {
		t.Fatalf("expected exactly 1 warmed container, got %v", warmed)
	}
	staleID := warmed[0]

	// Wait until the warmed container has less than a full run's timeout of
	// life left (remaining <= Timeout), which marks it stale.
	time.Sleep(60 * time.Millisecond)

	if _, _, _, err := p.Run(context.Background(), []byte("print('hi')")); err != nil {
		t.Fatalf("Run over a stale pool should succeed via inline replacement, got error: %v", err)
	}

	if !contains(rt.RemovedIDs(), staleID) {
		t.Fatalf("expected the stale container %q to be removed, removed=%v", staleID, rt.RemovedIDs())
	}
	execID := firstExecID(rt.Calls())
	if execID == "" {
		t.Fatalf("expected an Exec call, calls=%v", rt.Calls())
	}
	if execID == staleID {
		t.Fatalf("Run exec'd the stale container %q instead of a fresh replacement", staleID)
	}
}

// The age check must NOT recreate a healthy (fresh) container: a normal run
// execs the warmed container as-is, adding no replacement create on the hot
// path.
func TestPool_HealthyContainerUsedWithoutReplacement(t *testing.T) {
	rt := newFakeRuntime()
	p, err := sandbox.New(context.Background(), testConfig(1, time.Second), rt) // IdleTTL 1h
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}
	defer p.Close()

	warmed := rt.CreatedIDs()[0]

	if _, _, _, err := p.Run(context.Background(), []byte("print('hi')")); err != nil {
		t.Fatalf("Run: %v", err)
	}

	execID := firstExecID(rt.Calls())
	if execID != warmed {
		t.Fatalf("expected Run to exec the warmed container %q as-is, but exec'd %q (unexpected inline replacement)", warmed, execID)
	}
}
