// Package checkpoint implements whole-store checkpoint and restore for
// demo rollback (design D4, D8 in
// openspec/changes/apply-ontology-changes/design.md): a labelled
// checkpoint captures a full TriG export of the GraphDB repository (all
// named graphs, including staging and proposal graphs), a
// consistent-snapshot copy of the SQLite measurement store (taken with
// VACUUM INTO on a dedicated connection, never the chat path's
// read-only connection), and the ontology's owl:versionInfo value, all
// under data/checkpoints/{label}/. Restore reverses this: clear the
// repository, re-import the TriG, and atomically swap the live SQLite
// file for the checkpoint's copy.
package checkpoint

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/store"
)

// ErrNotFound is returned by Restore (and any label-scoped lookup) when
// no checkpoint directory exists for the given label. Callers (the HTTP
// layer) map it to a 404.
var ErrNotFound = errors.New("checkpoint: not found")

// storeFileName and dbFileName are the fixed artifact names written
// under each checkpoint's directory.
const (
	trigFileName     = "store.trig"
	sqliteFileName   = "msr.db"
	manifestFileName = "manifest.json"
)

// versionQuery reads the current ontology owl:versionInfo value via an
// explicit GRAPH scope (SelectRaw sends no dataset protocol params, so
// the graph must be named in the query itself). It intentionally
// matches at most one ontology header.
const versionQuery = `PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT ?v WHERE {
  GRAPH <urn:msr:ontology> { ?o a owl:Ontology ; owl:versionInfo ?v }
} LIMIT 1`

// GraphClient is the narrow, fakeable subset of *graph.Client the
// checkpoint engine uses: whole-repository export/clear/import plus a
// raw SELECT to read the ontology version header. Handlers and tests
// depend on this interface rather than *graph.Client directly (design
// D6).
type GraphClient interface {
	ExportRepo(ctx context.Context) ([]byte, error)
	ClearRepo(ctx context.Context) error
	ImportRepo(ctx context.Context, trig []byte) error
	SelectRaw(ctx context.Context, query string) (*graph.Results, error)
}

// Manifest is the recorded metadata for one checkpoint, persisted as
// manifest.json alongside the TriG export and SQLite copy.
type Manifest struct {
	Label           string `json:"label"`
	OntologyVersion string `json:"ontology_version"`
}

// Engine checkpoints and restores the whole store: the GraphDB
// repository reached through gc, and the SQLite measurement store at
// dbPath. root is the checkpoints base directory (e.g.
// "data/checkpoints"); each checkpoint lives under root/{label}/.
type Engine struct {
	gc     GraphClient
	dbPath string
	root   string
}

// NewEngine builds a checkpoint Engine. dbPath is the live SQLite
// measurement store file; root is the checkpoints base directory.
func NewEngine(gc GraphClient, dbPath, root string) *Engine {
	return &Engine{gc: gc, dbPath: dbPath, root: root}
}

// Create writes data/checkpoints/{label}/{store.trig, msr.db,
// manifest.json}: a full TriG export of the GraphDB repository, a
// VACUUM INTO snapshot of the live SQLite store, and a manifest
// recording the current ontology version. label is validated against
// the filesystem-safe charset (ValidateLabel) before any path is
// touched. The checkpoint directory must not already exist and be
// non-empty -- checkpoints are per-label and Create never silently
// overwrites one.
func (e *Engine) Create(ctx context.Context, label string) (Manifest, error) {
	if err := ValidateLabel(label); err != nil {
		return Manifest{}, err
	}

	trig, err := e.gc.ExportRepo(ctx)
	if err != nil {
		return Manifest{}, fmt.Errorf("checkpoint: export repo: %w", err)
	}

	version, err := e.readOntologyVersion(ctx)
	if err != nil {
		return Manifest{}, fmt.Errorf("checkpoint: read ontology version: %w", err)
	}

	dir := filepath.Join(e.root, label)
	if err := ensureFreshDir(dir); err != nil {
		return Manifest{}, err
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return Manifest{}, fmt.Errorf("checkpoint: create checkpoint dir %s: %w", dir, err)
	}

	if err := os.WriteFile(filepath.Join(dir, trigFileName), trig, 0o644); err != nil {
		return Manifest{}, fmt.Errorf("checkpoint: write %s: %w", trigFileName, err)
	}

	if err := e.snapshotSQLite(ctx, dir); err != nil {
		return Manifest{}, err
	}

	manifest := Manifest{Label: label, OntologyVersion: version}
	data, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return Manifest{}, fmt.Errorf("checkpoint: marshal manifest: %w", err)
	}
	if err := os.WriteFile(filepath.Join(dir, manifestFileName), data, 0o644); err != nil {
		return Manifest{}, fmt.Errorf("checkpoint: write %s: %w", manifestFileName, err)
	}

	return manifest, nil
}

// Restore clears the GraphDB repository, imports the checkpoint's
// store.trig, and atomically replaces the live SQLite file with the
// checkpoint's msr.db copy. label is validated before any path is
// touched; an unknown label yields ErrNotFound.
//
// ClearRepo and ImportRepo are two separate REST calls, not one
// transaction: if ImportRepo fails after ClearRepo already succeeded
// (transient network error, a SHACL shape added since the checkpoint
// was taken that now rejects its triples, disk error on GraphDB's
// side), the repository would otherwise be left completely empty with
// no way back -- strictly worse than the pre-restore state, on the
// very feature meant to be the safety net. To guard against that,
// Restore captures a full export of the CURRENT repository state
// before calling ClearRepo, and if the checkpoint import fails,
// attempts a best-effort re-import of that pre-clear snapshot so the
// repository ends up back where it started rather than empty. The
// returned error always distinguishes this partial-failure path from
// an ordinary no-op failure, and states plainly whether the rollback
// itself succeeded or the repository is now empty and needs manual
// intervention. The SQLite swap only ever runs after a successful
// graph import, so a graph-import failure (rolled back or not) never
// also swaps the live SQLite file.
func (e *Engine) Restore(ctx context.Context, label string) error {
	if err := ValidateLabel(label); err != nil {
		return err
	}

	dir := filepath.Join(e.root, label)
	if _, err := os.Stat(dir); err != nil {
		if os.IsNotExist(err) {
			return ErrNotFound
		}
		return fmt.Errorf("checkpoint: stat checkpoint dir %s: %w", dir, err)
	}

	trig, err := os.ReadFile(filepath.Join(dir, trigFileName))
	if err != nil {
		return fmt.Errorf("checkpoint: read %s: %w", trigFileName, err)
	}

	// Snapshot the CURRENT repo state in memory before clearing it, so a
	// failed checkpoint import can be rolled back rather than leaving the
	// repository empty.
	preClearSnapshot, err := e.gc.ExportRepo(ctx)
	if err != nil {
		return fmt.Errorf("checkpoint: snapshot pre-restore state: %w", err)
	}

	if err := e.gc.ClearRepo(ctx); err != nil {
		return fmt.Errorf("checkpoint: clear repo: %w", err)
	}

	if err := e.gc.ImportRepo(ctx, trig); err != nil {
		importErr := err
		if rbErr := e.gc.ImportRepo(ctx, preClearSnapshot); rbErr != nil {
			return fmt.Errorf(
				"checkpoint: restore failed and the repository was cleared; rollback to the pre-restore state ALSO failed -- the repository is now EMPTY and requires manual intervention (restore import err: %v, rollback err: %w)",
				importErr, rbErr,
			)
		}
		return fmt.Errorf(
			"checkpoint: restore failed after clearing the repository; attempted rollback to the pre-restore state and it succeeded, so the repository is unchanged from before this Restore call (restore import err: %w)",
			importErr,
		)
	}

	if err := e.swapSQLite(dir); err != nil {
		return err
	}
	return nil
}

// List enumerates the checkpoints under root by reading each
// subdirectory's manifest.json. Subdirectories without a manifest are
// skipped (they are not a valid checkpoint); the result is sorted by
// label for a deterministic order.
func (e *Engine) List() ([]Manifest, error) {
	entries, err := os.ReadDir(e.root)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("checkpoint: read checkpoints dir %s: %w", e.root, err)
	}

	var manifests []Manifest
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		manifestPath := filepath.Join(e.root, entry.Name(), manifestFileName)
		data, err := os.ReadFile(manifestPath)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return nil, fmt.Errorf("checkpoint: read manifest %s: %w", manifestPath, err)
		}
		var m Manifest
		if err := json.Unmarshal(data, &m); err != nil {
			return nil, fmt.Errorf("checkpoint: parse manifest %s: %w", manifestPath, err)
		}
		manifests = append(manifests, m)
	}

	sort.Slice(manifests, func(i, j int) bool { return manifests[i].Label < manifests[j].Label })
	return manifests, nil
}

// readOntologyVersion reads owl:versionInfo from the urn:msr:ontology
// graph header. If the query runs but no ontology header is found
// (zero bindings -- e.g. an empty or malformed repository), an empty
// string is recorded rather than failing the whole checkpoint: the
// version is metadata for display/diagnostics, not something the
// round-trip depends on for correctness, so a missing value should not
// block capturing the graph and SQLite state. A transport/query error
// from SelectRaw itself is still propagated as a real failure.
func (e *Engine) readOntologyVersion(ctx context.Context) (string, error) {
	res, err := e.gc.SelectRaw(ctx, versionQuery)
	if err != nil {
		return "", err
	}
	for _, row := range res.Results.Bindings {
		if b, ok := row["v"]; ok {
			return b.Value, nil
		}
	}
	return "", nil
}

// ensureFreshDir errors if dir already exists and is non-empty:
// checkpoints are per-label and Create must never silently overwrite
// one. A missing or empty directory is fine (the caller creates/reuses
// it next).
func ensureFreshDir(dir string) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("checkpoint: stat checkpoint dir %s: %w", dir, err)
	}
	if len(entries) > 0 {
		return fmt.Errorf("checkpoint: checkpoint %q already exists", filepath.Base(dir))
	}
	return nil
}

// snapshotSQLite takes a consistent copy of the live SQLite measurement
// store into dir/msr.db via VACUUM INTO on a dedicated read-write
// connection opened on e.dbPath -- deliberately not the chat request
// path's mode=ro&query_only connection (readOnlyMeasurementStoreDSN in
// cmd/server/main.go), since query_only forbids VACUUM and mode=ro
// would make the snapshot target unreachable from that connection
// anyway. store.Open's plain read-write DSN (journal_mode=DELETE,
// busy_timeout) is reused so this connection follows the same
// conventions as every other writer of the measurement store.
// VACUUM INTO requires the target file not already exist; the caller
// (Create) only calls this against a freshly created checkpoint
// directory, so msr.db is guaranteed absent.
func (e *Engine) snapshotSQLite(ctx context.Context, dir string) error {
	db, err := store.Open(e.dbPath)
	if err != nil {
		return fmt.Errorf("checkpoint: open sqlite snapshot connection: %w", err)
	}
	defer db.Close()

	target, err := filepath.Abs(filepath.Join(dir, sqliteFileName))
	if err != nil {
		return fmt.Errorf("checkpoint: resolve sqlite snapshot target: %w", err)
	}

	if _, err := db.ExecContext(ctx, "VACUUM INTO ?", target); err != nil {
		return fmt.Errorf("checkpoint: vacuum into %s: %w", target, err)
	}
	return nil
}

// swapSQLite atomically replaces the live SQLite file (e.dbPath) with
// the checkpoint's msr.db copy found under checkpointDir: the copy is
// first written to a temp file in the live file's own directory, then
// moved onto e.dbPath with os.Rename, which is atomic within the same
// filesystem.
func (e *Engine) swapSQLite(checkpointDir string) error {
	data, err := os.ReadFile(filepath.Join(checkpointDir, sqliteFileName))
	if err != nil {
		return fmt.Errorf("checkpoint: read %s: %w", sqliteFileName, err)
	}

	destDir := filepath.Dir(e.dbPath)
	tmp, err := os.CreateTemp(destDir, ".msr-restore-*.db")
	if err != nil {
		return fmt.Errorf("checkpoint: create temp file for sqlite swap: %w", err)
	}
	tmpPath := tmp.Name()

	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		os.Remove(tmpPath)
		return fmt.Errorf("checkpoint: write temp sqlite file: %w", err)
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("checkpoint: close temp sqlite file: %w", err)
	}

	if err := os.Rename(tmpPath, e.dbPath); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("checkpoint: swap sqlite file: %w", err)
	}
	return nil
}
