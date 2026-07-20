package sandbox

import (
	"context"
	"errors"
	"fmt"
	"log"
	"sync"
	"time"
)

// ErrTimeout is returned by Run when a script run is terminated because it
// exceeded the pool's configured wall-clock timeout. It is distinguishable
// from a normal non-zero exit code (design D6, D7): a caller can render
// "script exceeded time limit" in the trace rather than treating it as a
// script-level failure.
var ErrTimeout = errors.New("sandbox: run exceeded wall-clock timeout")

// errClosed is returned by Run when it is called (or is blocked waiting to
// acquire a container) after the pool has been closed.
var errClosed = errors.New("sandbox: pool is closed")

// Bounded backoff for replenishment retries: a persistently failing daemon
// must never make the replenishment goroutine busy-spin (design D8).
const (
	replenishInitialBackoff = 200 * time.Millisecond
	replenishMaxBackoff     = 30 * time.Second
)

// container is the pool's internal handle for one warm, ready sandbox: its
// id plus the wall-clock instant at which its bounded `sleep <IdleTTL>` PID 1
// exits and AutoRemove deletes it. `expires` lets Run reject a container that
// has sat idle long enough to self-reap before handing it out -- otherwise a
// pool left idle longer than IdleTTL would dispense already-removed ids and
// exec would fail with "No such container" (design D1/D9).
type warmContainer struct {
	id      string
	expires time.Time
}

// Pool is a fixed-size warm pool of single-use sandbox containers. The
// buffered channel `ready` IS the pool (design D1): acquiring a container is
// a channel receive, which blocks when the pool is empty and so bounds
// concurrency at the pool's configured size. A container serves exactly one
// script run; afterward it is force-removed and a background goroutine
// creates and enqueues a replacement. There is deliberately no
// return-to-pool path.
type Pool struct {
	rt      Runtime
	spec    ContainerSpec
	timeout time.Duration

	ready chan warmContainer

	done      chan struct{}
	closeOnce sync.Once

	// mu guards closed and serializes replenishment spawns against Close, so
	// that no wg.Add can ever happen after Close's wg.Wait has returned
	// (which would both be a WaitGroup misuse and risk enqueuing a freshly
	// created container into ready after Close has already drained it,
	// orphaning it and violating design D8).
	mu     sync.Mutex
	closed bool

	wg sync.WaitGroup
}

// New creates a Pool backed by rt, configured by cfg.
//
// It first calls rt.Reap to force-remove any containers left behind by a
// previous, non-gracefully-stopped server process (the startup sweep, design
// D9) before warming anything -- so a restarted server always begins from a
// clean slate. It then eagerly creates cfg.PoolSize warm containers and
// enqueues them.
//
// New fails fast: if Reap or any initial Create fails, it force-removes any
// containers already created during this call and returns a descriptive
// error, so misconfiguration (bad image, unreachable daemon, ...) surfaces
// at startup rather than mid-demo (design D8).
func New(ctx context.Context, cfg Config, rt Runtime) (*Pool, error) {
	if cfg.PoolSize <= 0 {
		return nil, fmt.Errorf("sandbox: invalid config: PoolSize must be > 0, got %d", cfg.PoolSize)
	}
	if cfg.Timeout <= 0 {
		return nil, fmt.Errorf("sandbox: invalid config: Timeout must be > 0, got %s", cfg.Timeout)
	}
	if cfg.IdleTTL <= cfg.Timeout {
		return nil, fmt.Errorf("sandbox: invalid config: IdleTTL (%s) must exceed Timeout (%s)", cfg.IdleTTL, cfg.Timeout)
	}

	if err := rt.Reap(ctx); err != nil {
		return nil, fmt.Errorf("sandbox: startup sweep (Reap) failed: %w", err)
	}

	spec := ContainerSpec{
		Image:       cfg.Image,
		DataHostDir: cfg.DataHostDir,
		CPUs:        cfg.CPUs,
		MemoryBytes: cfg.MemoryBytes,
		PidsLimit:   cfg.PidsLimit,
		TmpfsSize:   cfg.TmpfsSize,
		IdleTTL:     cfg.IdleTTL,
		Labels:      map[string]string{SandboxLabel: "1"},
	}

	p := &Pool{
		rt:      rt,
		spec:    spec,
		timeout: cfg.Timeout,
		ready:   make(chan warmContainer, cfg.PoolSize),
		done:    make(chan struct{}),
	}

	created := make([]string, 0, cfg.PoolSize)
	for i := 0; i < cfg.PoolSize; i++ {
		id, err := rt.Create(ctx, spec)
		if err != nil {
			for _, cid := range created {
				if rmErr := rt.Remove(context.Background(), cid); rmErr != nil {
					log.Printf("sandbox: failed to remove container %s while rolling back a failed startup warm: %v", cid, rmErr)
				}
			}
			return nil, fmt.Errorf("sandbox: failed to warm initial pool (created %d/%d): %w", i, cfg.PoolSize, err)
		}
		created = append(created, id)
		p.ready <- warmContainer{id: id, expires: time.Now().Add(spec.IdleTTL)}
	}

	return p, nil
}

// Run acquires one warm container, executes script on it as a single
// `python -` run, and always tears the container down afterward -- whatever
// the outcome (success, non-zero exit, exec error, or timeout) -- so no
// state ever survives from one run to the next (design D1).
//
// A non-zero script exit code is a normal result: stdout, stderr, and
// exitCode are returned verbatim with a nil error (design D6). error is
// reserved for: the caller's ctx being cancelled, the run exceeding the
// pool's configured wall-clock timeout (ErrTimeout, design D7), or an
// infrastructure/daemon failure from the Runtime.
func (p *Pool) Run(ctx context.Context, script []byte) (stdout, stderr []byte, exitCode int, err error) {
	var c warmContainer
	select {
	case <-ctx.Done():
		return nil, nil, 0, fmt.Errorf("sandbox: %w", ctx.Err())
	case <-p.done:
		return nil, nil, 0, errClosed
	case c = <-p.ready:
	}

	// Age-aware acquisition (fixes the stale-container "No such container"
	// failure): a warm container's PID 1 is `sleep <IdleTTL>` with
	// AutoRemove, so one that has sat idle in the pool long enough has already
	// exited and been removed. If the acquired container lacks enough
	// remaining lifetime to outlast a full run (guarding both the
	// already-reaped and the would-reap-mid-run cases), discard it and create
	// a fresh replacement inline so this run succeeds instead of erroring on a
	// vanished container. During active use containers are freshly replenished
	// and this branch never trips, so it adds no steady-state latency.
	if time.Until(c.expires) <= p.timeout {
		if rmErr := p.rt.Remove(context.Background(), c.id); rmErr != nil {
			log.Printf("sandbox: failed to remove stale warm container %s before replacing it: %v", c.id, rmErr)
		}
		id, createErr := p.rt.Create(ctx, p.spec)
		if createErr != nil {
			// Keep the pool topped up (we consumed a slot), then surface it.
			p.startReplenish()
			return nil, nil, 0, fmt.Errorf("sandbox: create replacement for stale warm container: %w", createErr)
		}
		c = warmContainer{id: id, expires: time.Now().Add(p.spec.IdleTTL)}
	}

	runCtx, cancel := context.WithTimeout(ctx, p.timeout)
	defer cancel()

	res, execErr := p.rt.Exec(runCtx, c.id, script)

	// Always force-remove the used container, whatever happened. Use a
	// detached context so removal still runs even though runCtx may already
	// be past its deadline or cancelled (design D1, D7).
	if rmErr := p.rt.Remove(context.Background(), c.id); rmErr != nil {
		log.Printf("sandbox: failed to remove used container %s: %v", c.id, rmErr)
	}

	// Replenishment happens off the request path (design D1, D8).
	p.startReplenish()

	// The caller's ctx is checked first so ErrTimeout is only reported when
	// the pool's own timer fired while the caller's ctx was still live --
	// otherwise a caller-supplied ctx deadline would be misreported as the
	// pool's ErrTimeout, since runCtx inherits ctx's deadline too.
	switch {
	case ctx.Err() != nil:
		return nil, nil, 0, fmt.Errorf("sandbox: %w", ctx.Err())
	case errors.Is(runCtx.Err(), context.DeadlineExceeded):
		return nil, nil, 0, ErrTimeout
	case execErr != nil:
		return nil, nil, 0, fmt.Errorf("sandbox: exec failed: %w", execErr)
	default:
		return res.Stdout, res.Stderr, res.ExitCode, nil
	}
}

// startReplenish registers and starts a replenish goroutine, unless the pool
// is already closed. Registering the wg.Add under the same mutex that Close
// sets closed and closes done under guarantees every wg.Add happens-before
// Close's wg.Wait -- so Close can never return while a replenishment it
// didn't know about is still in flight, and no post-close replenish can slip
// a container into ready after Close has already drained it (design D8).
func (p *Pool) startReplenish() {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.closed {
		return
	}
	p.wg.Add(1)
	go p.replenish()
}

// replenish creates one fresh container and enqueues it into ready,
// replacing the one just consumed by Run. It retries Create with bounded
// backoff on failure -- never busy-spinning -- so a persistently failing
// daemon simply shrinks the effective pool rather than deadlocking or
// spinning (design D8). It selects on the pool's done signal at every step:
// if the pool is closing, it stops without sending into ready (a post-close
// send would leak an unaccounted-for container), force-removing any
// container it had already created.
func (p *Pool) replenish() {
	defer p.wg.Done()

	backoff := replenishInitialBackoff
	for {
		select {
		case <-p.done:
			return
		default:
		}

		id, err := p.rt.Create(context.Background(), p.spec)
		if err != nil {
			log.Printf("sandbox: replenish: create failed, retrying in %s: %v", backoff, err)
			select {
			case <-p.done:
				return
			case <-time.After(backoff):
			}
			backoff *= 2
			if backoff > replenishMaxBackoff {
				backoff = replenishMaxBackoff
			}
			continue
		}

		select {
		case <-p.done:
			if rmErr := p.rt.Remove(context.Background(), id); rmErr != nil {
				log.Printf("sandbox: failed to remove freshly created container %s during shutdown: %v", id, rmErr)
			}
			return
		case p.ready <- warmContainer{id: id, expires: time.Now().Add(p.spec.IdleTTL)}:
			return
		}
	}
}

// Close gracefully shuts the pool down: it stops replenishment, waits for
// any outstanding replenishment goroutines to finish, and then force-removes
// every idle container left in ready, so a graceful shutdown leaves no
// orphaned sandboxes (design D8). It is idempotent and safe to call more
// than once. It returns the first removal error encountered, if any.
//
// Close waits for outstanding replenishment goroutines to finish *before*
// draining ready: every such goroutine either enqueues its freshly created
// container into ready or force-removes it itself before returning, so by
// the time the wait completes, ready holds exactly the containers left to
// clean up here -- nothing is dropped and nothing is drained out from under
// a goroutine still in flight.
//
// closed is set and done is closed under the same mutex startReplenish
// locks, before wg.Wait is called, so every wg.Add is guaranteed to have
// happened-before this wg.Wait (see startReplenish). Note that because
// replenish creates containers with a detached context.Background(), a
// Close concurrent with a replenish blocked inside a wedged daemon Create
// call can block in wg.Wait until that call returns; this is an accepted
// trade-off, since abandoning the wait would risk leaving a half-created
// container un-tracked and un-removed.
func (p *Pool) Close() error {
	var err error
	p.closeOnce.Do(func() {
		p.mu.Lock()
		p.closed = true
		close(p.done)
		p.mu.Unlock()

		p.wg.Wait()

		for {
			select {
			case c := <-p.ready:
				if rmErr := p.rt.Remove(context.Background(), c.id); rmErr != nil {
					log.Printf("sandbox: failed to remove idle container %s during close: %v", c.id, rmErr)
					if err == nil {
						err = rmErr
					}
				}
			default:
				return
			}
		}
	})
	return err
}
