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

func contains(ids []string, id string) bool {
	for _, v := range ids {
		if v == id {
			return true
		}
	}
	return false
}
