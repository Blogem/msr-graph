package sandbox_test

// fakeRuntime is an in-memory sandbox.Runtime used by the pool's unit tests
// (tasks 6.1-6.7, design D2): it drives drain/replenish, timeout, and
// concurrency behavior with no Docker daemon present. It is safe for
// concurrent use -- pool_test.go exercises it under `-race` with many
// concurrent Run calls (6.5).
//
// Container ids are a monotonic counter ("c1", "c2", ...) assigned in Create
// call-completion order.

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/blogem/msr-graph/internal/sandbox"
)

// callMethod names one fakeRuntime call for the ordered call log.
type callMethod string

const (
	callCreate callMethod = "Create"
	callExec   callMethod = "Exec"
	callRemove callMethod = "Remove"
	callReap   callMethod = "Reap"
)

// callRecord captures one completed call, in completion order, for tests
// that assert call ordering (e.g. Reap before the first Create, or
// Exec -> Remove -> Create for drain/replenish).
type callRecord struct {
	Method callMethod
	ID     string // empty for Reap
}

// execScript is a scripted Exec response for one container id.
type execScript struct {
	result sandbox.ExecResult
	err    error
}

// fakeRuntime implements sandbox.Runtime in memory. Zero value is not
// ready for use; construct with newFakeRuntime.
type fakeRuntime struct {
	mu sync.Mutex

	idSeq int

	calls []callRecord

	createdIDs        []string
	createdSpecs      []sandbox.ContainerSpec
	removedIDs        []string
	execedIDs         []string
	reapCalls         int
	reapRemovedByCall [][]string

	// seeded holds pre-existing labelled container ids that Reap force-
	// removes on its next call (6.7, startup sweep).
	seeded []string

	// Injected errors, applied to every subsequent call to the respective
	// method until cleared.
	createErr error
	removeErr error
	reapErr   error

	// Injected artificial delays, applied to every subsequent call.
	createDelay time.Duration
	execDelay   time.Duration

	// hangExec, when true, makes every Exec call block until its ctx is
	// done and then return ctx.Err() -- drives the timeout test (6.3).
	hangExec bool

	// defaultExec is returned by Exec when the called id has no
	// per-id script.
	defaultExec    sandbox.ExecResult
	defaultExecErr error

	// perID holds per-container-id scripted Exec responses, keyed by id.
	perID map[string]execScript
}

var _ sandbox.Runtime = (*fakeRuntime)(nil)

// newFakeRuntime returns a ready-to-use fakeRuntime with no injected
// delays, errors, or scripted output (Exec returns the zero ExecResult
// and a nil error by default).
func newFakeRuntime() *fakeRuntime {
	return &fakeRuntime{
		perID: make(map[string]execScript),
	}
}

// --- sandbox.Runtime ---

func (f *fakeRuntime) Create(ctx context.Context, spec sandbox.ContainerSpec) (string, error) {
	f.mu.Lock()
	err := f.createErr
	delay := f.createDelay
	f.mu.Unlock()

	if err != nil {
		return "", err
	}

	if delay > 0 {
		select {
		case <-time.After(delay):
		case <-ctx.Done():
			return "", ctx.Err()
		}
	}

	f.mu.Lock()
	f.idSeq++
	id := fmt.Sprintf("c%d", f.idSeq)
	f.createdIDs = append(f.createdIDs, id)
	f.createdSpecs = append(f.createdSpecs, spec)
	f.calls = append(f.calls, callRecord{Method: callCreate, ID: id})
	f.mu.Unlock()

	return id, nil
}

func (f *fakeRuntime) Exec(ctx context.Context, id string, script []byte) (sandbox.ExecResult, error) {
	f.mu.Lock()
	f.execedIDs = append(f.execedIDs, id)
	f.calls = append(f.calls, callRecord{Method: callExec, ID: id})
	hang := f.hangExec
	delay := f.execDelay
	result := f.defaultExec
	resultErr := f.defaultExecErr
	if s, ok := f.perID[id]; ok {
		result = s.result
		resultErr = s.err
	}
	f.mu.Unlock()

	if hang {
		<-ctx.Done()
		return sandbox.ExecResult{}, ctx.Err()
	}

	if delay > 0 {
		select {
		case <-time.After(delay):
		case <-ctx.Done():
			return sandbox.ExecResult{}, ctx.Err()
		}
	}

	return result, resultErr
}

func (f *fakeRuntime) Remove(ctx context.Context, id string) error {
	f.mu.Lock()
	defer f.mu.Unlock()

	if f.removeErr != nil {
		return f.removeErr
	}
	f.removedIDs = append(f.removedIDs, id)
	f.calls = append(f.calls, callRecord{Method: callRemove, ID: id})
	return nil
}

func (f *fakeRuntime) Reap(ctx context.Context) error {
	f.mu.Lock()
	defer f.mu.Unlock()

	if f.reapErr != nil {
		return f.reapErr
	}

	f.reapCalls++
	removed := append([]string(nil), f.seeded...)
	f.reapRemovedByCall = append(f.reapRemovedByCall, removed)
	f.calls = append(f.calls, callRecord{Method: callReap})
	f.removedIDs = append(f.removedIDs, removed...)
	f.seeded = nil
	return nil
}

// --- programming knobs ---

// seedLabelled registers pre-existing labelled container ids that the next
// Reap call force-removes (models orphans left by a prior server process).
func (f *fakeRuntime) seedLabelled(ids ...string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.seeded = append(f.seeded, ids...)
}

func (f *fakeRuntime) setCreateErr(err error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.createErr = err
}

func (f *fakeRuntime) setRemoveErr(err error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.removeErr = err
}

func (f *fakeRuntime) setReapErr(err error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.reapErr = err
}

func (f *fakeRuntime) setCreateDelay(d time.Duration) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.createDelay = d
}

func (f *fakeRuntime) setExecDelay(d time.Duration) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.execDelay = d
}

// setHangExec makes every subsequent Exec call block until its ctx is done,
// then return ctx.Err(). Used to drive the wall-clock timeout test (6.3).
func (f *fakeRuntime) setHangExec(hang bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.hangExec = hang
}

// setDefaultExec sets the ExecResult/error returned by Exec for any
// container id with no per-id script.
func (f *fakeRuntime) setDefaultExec(result sandbox.ExecResult, err error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.defaultExec = result
	f.defaultExecErr = err
}

// setExecFor scripts the ExecResult/error returned by Exec for one specific
// container id, overriding the default for that id only.
func (f *fakeRuntime) setExecFor(id string, result sandbox.ExecResult, err error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.perID[id] = execScript{result: result, err: err}
}

// --- query helpers (all return copies, safe to call concurrently) ---

func (f *fakeRuntime) Calls() []callRecord {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]callRecord(nil), f.calls...)
}

func (f *fakeRuntime) CreatedIDs() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.createdIDs...)
}

func (f *fakeRuntime) CreatedSpecs() []sandbox.ContainerSpec {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]sandbox.ContainerSpec(nil), f.createdSpecs...)
}

func (f *fakeRuntime) RemovedIDs() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.removedIDs...)
}

func (f *fakeRuntime) ExecedIDs() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.execedIDs...)
}

func (f *fakeRuntime) ReapCalls() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.reapCalls
}

// CreateCount, RemoveCount, and ExecCount report how many times each method
// has completed so far.
func (f *fakeRuntime) CreateCount() int { return len(f.CreatedIDs()) }
func (f *fakeRuntime) RemoveCount() int { return len(f.RemovedIDs()) }
func (f *fakeRuntime) ExecCount() int   { return len(f.ExecedIDs()) }
