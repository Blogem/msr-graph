package scripts

// Test for task 7.7 / design D7 ("ensure-repo.sh detects and warns on a
// non-SHACL existing repo"), plus coverage added for the
// isolate-integration-test-repo change (design D4: REPO_ID / REPO_RESET).
// scripts/ensure-repo.sh is a forbidden path for this change (read-only)
// -- so this test can never safely point the real, unmodified script at a
// throwaway repo id on a live GraphDB without risking the real "msr"
// repository (which the task contract explicitly forbids clobbering).
//
// Per the task contract's documented fallback ("if a full live test is
// impractical, at minimum test the script's SHACL-detection logic...
// document what is and isn't exercised"), this test instead runs the
// REAL, unmodified script end-to-end against a fully local
// httptest.Server standing in for GraphDB's REST API. Nothing here EVER
// touches a real GraphDB instance or a real "msr" repository, no matter
// what repo id the script targets -- the "msr" (or "msr-test") the script
// sees only exists inside this test's in-memory double. Because of that,
// this test does NOT need to be gated behind requireGraphDB/GRAPHDB_REQUIRED
// (no external GraphDB dependency at all): it is a hermetic test that
// should run in any environment with bash + curl available.
//
// What IS exercised:
//   - the idempotent check-then-create path already implemented today
//     (GET /rest/repositories, grep-for-id, no-op on match) --
//     unaffected by task 1.4's D7 addition, so
//     TestEnsureRepo_NoOpWhenRepoAlreadyExists is expected to pass
//     immediately, pre- and post-merge.
//   - the D7 detection: the pass/fail branch based on whichever GraphDB
//     endpoint that detection queries for the existing repo's sail
//     config (GET /rest/repositories/<id> or GET /repositories/<id>/config
//     -- this double serves both routes).
//   - the REPO_ID override (isolate-integration-test-repo D4): pointing
//     the script at a non-"msr" repo id drives the create-POST path and
//     is not silently ignored.
//   - the REPO_RESET=1 reset path: a DELETE /rest/repositories/<id> is
//     issued before create when REPO_RESET=1 and REPO_ID != "msr".
//   - the REPO_RESET guard: REPO_ID=msr together with REPO_RESET=1 is
//     refused (non-zero exit) without ever issuing the DELETE.
//
// What is NOT exercised:
//   - real GraphDB wire behavior/response shape for the config-inspection
//     call (this is a double, not a live round-trip);
//   - the real repo-creation POST's interaction with an actual
//     SHACL-enabled config;
//   - the real sed-based repositoryID substitution's effect on GraphDB
//     (the double doesn't parse the POSTed config body's contents, just
//     records that a create POST occurred).

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"testing"
)

// repoRoot locates the module root from this test file's own path.
func repoRoot(t *testing.T) string {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("repoRoot: runtime.Caller failed")
	}
	// thisFile: <repoRoot>/scripts/ensure-repo_test.go
	return filepath.Dir(filepath.Dir(thisFile))
}

// ensureRepoScriptPath returns the path to the real, unmodified
// scripts/ensure-repo.sh, failing loudly if it is missing (this test must
// never silently no-op).
func ensureRepoScriptPath(t *testing.T, root string) string {
	t.Helper()
	p := filepath.Join(root, "scripts", "ensure-repo.sh")
	if _, err := os.Stat(p); err != nil {
		t.Fatalf("scripts/ensure-repo.sh not found at %s: %v", p, err)
	}
	return p
}

// runEnsureRepo runs the real scripts/ensure-repo.sh with GRAPHDB_URL
// pointed at baseURL (a local double, never a real GraphDB) and returns
// its exit error (nil on success) and combined stdout+stderr. extraEnv
// entries (e.g. "REPO_ID=msr-test", "REPO_RESET=1") are appended to the
// child's environment, letting tests exercise the D4 REPO_ID/REPO_RESET
// overrides without touching the default "msr" behavior.
func runEnsureRepo(t *testing.T, root, baseURL string, extraEnv ...string) (error, string) {
	t.Helper()
	cmd := exec.Command(ensureRepoScriptPath(t, root))
	cmd.Dir = root
	env := append(os.Environ(), "GRAPHDB_URL="+baseURL)
	env = append(env, extraEnv...)
	cmd.Env = env
	out, err := cmd.CombinedOutput()
	return err, string(out)
}

// shaclEnabledConfigDouble / nonShaclConfigDouble stand in for whatever
// GraphDB returns for the existing repo's config, shaped per design D1's
// pinned sail-type/param names. The sail-type literal is confirmed as
// `rdf4j:ShaclSail` on GraphDB 11.4.2 (design D1's round-trip check),
// NOT `graphdb:ShaclSail`. The real response schema for D7's chosen
// endpoint is not finalized as of this test's authoring (task 1.4 lands
// in parallel) -- see the file-level coverage note.
const shaclEnabledConfigDouble = `
@prefix sail-shacl: <http://rdf4j.org/config/sail/shacl#> .
[] a rep:RepositoryContext ;
   rep:repositoryImpl [
       sail:sailType "rdf4j:ShaclSail" ;
       sail-shacl:validationEnabled true ;
       sail-shacl:shapesGraph <http://rdf4j.org/schema/rdf4j#SHACLShapeGraph>
   ] .
`

const nonShaclConfigDouble = `
[] a rep:RepositoryContext ;
   rep:repositoryImpl [
       sail:sailType "graphdb:Sail" ;
       graphdb:ruleset "empty"
   ] .
`

// repositoriesListBody is the GET /rest/repositories response body
// listing a single existing repository "msr" -- matches ensure-repo.sh's
// current grep pattern (`"id"[[:space:]]*:[[:space:]]*"msr"`) exactly.
const repositoriesListBody = `[{"id":"msr","title":"msr","uri":"http://example.invalid/repositories/msr"}]`

// newEnsureRepoDouble builds a local GraphDB REST API double: it always
// reports "msr" as already existing (so the script's check-then-create
// takes the "already exists" branch, per this test's contract-required
// scenarios), and serves configBody from the two candidate config-
// inspection endpoints design.md names. createCalls counts any POST
// /rest/repositories the script issues, so tests can assert the
// already-exists branch never attempts a duplicate create.
//
// Post-merge, ensure-repo.sh also loads the shape catalogue into the
// reserved shapes graph via the Graph Store Protocol (PUT the
// hand-authored shapes, then POST the generated unit fragment) against
// /repositories/msr/rdf-graphs/service?graph=<reserved-graph-iri>,
// regardless of which check-then-create branch was taken. This double
// answers BOTH verbs on that path with 204 No Content (Graph Store
// Protocol's usual "operation succeeded, no body" response) so the
// script's shapes-load step -- unrelated to what these two tests are
// actually pinning (D7 detection) -- doesn't 404 and abort the script.
func newEnsureRepoDouble(t *testing.T, configBody string, createCalls *int32) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/rest/repositories":
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprint(w, repositoriesListBody)
		case r.Method == http.MethodPost && r.URL.Path == "/rest/repositories":
			atomic.AddInt32(createCalls, 1)
			w.WriteHeader(http.StatusCreated)
		case r.Method == http.MethodGet && (r.URL.Path == "/rest/repositories/msr" || r.URL.Path == "/repositories/msr/config"):
			w.Header().Set("Content-Type", "text/turtle")
			fmt.Fprint(w, configBody)
		case (r.Method == http.MethodPut || r.Method == http.MethodPost) && r.URL.Path == "/repositories/msr/rdf-graphs/service":
			w.WriteHeader(http.StatusNoContent)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
}

// TestEnsureRepo_NoOpWhenRepoAlreadyExists pins the idempotent
// check-then-create half of task 7.7: when GET /rest/repositories already
// lists "msr", the script must exit 0 without attempting a create POST.
// This part of ensure-repo.sh's behavior is already implemented today
// (unaffected by task 1.4's D7 addition), so this test is expected to
// pass immediately, pre- and post-merge.
func TestEnsureRepo_NoOpWhenRepoAlreadyExists(t *testing.T) {
	root := repoRoot(t)

	var createCalls int32
	srv := newEnsureRepoDouble(t, shaclEnabledConfigDouble, &createCalls)
	defer srv.Close()

	err, out := runEnsureRepo(t, root, srv.URL)
	if err != nil {
		t.Fatalf("ensure-repo.sh failed against an already-existing (SHACL-enabled) repo double: %v\noutput:\n%s", err, out)
	}
	if got := atomic.LoadInt32(&createCalls); got != 0 {
		t.Errorf("ensure-repo.sh issued %d create POST(s) for an already-existing repo, want 0 (must be a no-op)", got)
	}
}

// TestEnsureRepo_FailsWithGuidanceOnNonSHACLExistingRepo pins design D7 /
// task 1.4 / task 7.7's "fails with guidance when the existing repo is
// not SHACL-enabled" scenario. It is authored against the CONTRACT, not
// against today's script (D7 detection does not exist yet in this
// worktree as of pass 1) -- expected to fail until task 1.4 lands, per
// pass-1 convention ("tests that exercise new implementation are
// EXPECTED to fail... in your worktree").
func TestEnsureRepo_FailsWithGuidanceOnNonSHACLExistingRepo(t *testing.T) {
	root := repoRoot(t)

	var createCalls int32
	srv := newEnsureRepoDouble(t, nonShaclConfigDouble, &createCalls)
	defer srv.Close()

	err, out := runEnsureRepo(t, root, srv.URL)
	if err == nil {
		t.Fatalf("expected scripts/ensure-repo.sh to fail (non-zero exit) when the existing repo is not SHACL-enabled, but it succeeded; output:\n%s", out)
	}
	lower := strings.ToLower(out)
	if !strings.Contains(lower, "shacl") {
		t.Errorf("expected ensure-repo.sh's failure output to mention SHACL (guidance for the operator), got:\n%s", out)
	}
}

// newRepoDouble builds a local GraphDB REST API double parameterized by
// repoID, for exercising the REPO_ID override and REPO_RESET paths added
// by the isolate-integration-test-repo change (design D4). Unlike
// newEnsureRepoDouble above (which is pinned to "msr" for the pre-existing
// D7 tests), this double's routes key off repoID so it can stand in for
// "msr-test" or any other id.
//
//   - exists controls whether GET /rest/repositories reports repoID as
//     already present (driving the script's no-op/exists branch) or absent
//     (driving the create branch).
//   - configBody is served from both config-inspection candidate endpoints
//     design.md names, same as newEnsureRepoDouble.
//   - createCalls / deleteCalls count POST /rest/repositories and
//     DELETE /rest/repositories/<repoID> respectively; either may be nil
//     if a given test doesn't need that assertion.
func newRepoDouble(t *testing.T, repoID string, exists bool, configBody string, createCalls, deleteCalls *int32) *httptest.Server {
	t.Helper()

	repositoriesListBody := "[]"
	if exists {
		repositoriesListBody = fmt.Sprintf(
			`[{"id":%q,"title":%q,"uri":"http://example.invalid/repositories/%s"}]`,
			repoID, repoID, repoID,
		)
	}

	deletePath := "/rest/repositories/" + repoID
	configPath1 := "/rest/repositories/" + repoID
	configPath2 := "/repositories/" + repoID + "/config"
	rdfGraphsPath := "/repositories/" + repoID + "/rdf-graphs/service"

	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/rest/repositories":
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprint(w, repositoriesListBody)
		case r.Method == http.MethodDelete && r.URL.Path == deletePath:
			if deleteCalls != nil {
				atomic.AddInt32(deleteCalls, 1)
			}
			// Tolerate both "existed and was dropped" (204) and
			// "didn't exist" (404) per the script's documented contract;
			// 204 exercises the common case here.
			w.WriteHeader(http.StatusNoContent)
		case r.Method == http.MethodPost && r.URL.Path == "/rest/repositories":
			if createCalls != nil {
				atomic.AddInt32(createCalls, 1)
			}
			w.WriteHeader(http.StatusCreated)
		case r.Method == http.MethodGet && (r.URL.Path == configPath1 || r.URL.Path == configPath2):
			w.Header().Set("Content-Type", "text/turtle")
			fmt.Fprint(w, configBody)
		case (r.Method == http.MethodPut || r.Method == http.MethodPost) && r.URL.Path == rdfGraphsPath:
			w.WriteHeader(http.StatusNoContent)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
}

// TestEnsureRepo_RepoIDOverride_CreatesNonMsrRepo pins design D4's REPO_ID
// override: pointing the script at a not-yet-existing "msr-test" repo
// drives the create-POST path (never silently ignored / never falls back
// to "msr").
func TestEnsureRepo_RepoIDOverride_CreatesNonMsrRepo(t *testing.T) {
	root := repoRoot(t)

	var createCalls int32
	srv := newRepoDouble(t, "msr-test", false, shaclEnabledConfigDouble, &createCalls, nil)
	defer srv.Close()

	err, out := runEnsureRepo(t, root, srv.URL, "REPO_ID=msr-test")
	if err != nil {
		t.Fatalf("ensure-repo.sh failed with REPO_ID=msr-test override: %v\noutput:\n%s", err, out)
	}
	if got := atomic.LoadInt32(&createCalls); got != 1 {
		t.Errorf("ensure-repo.sh issued %d create POST(s) for a not-yet-existing 'msr-test' repo, want 1", got)
	}
	if !strings.Contains(out, "msr-test") {
		t.Errorf("expected ensure-repo.sh output to reference 'msr-test', got:\n%s", out)
	}
}

// TestEnsureRepo_ResetDropsNonMsrRepoBeforeCreate pins design D4's
// REPO_RESET=1 path: for a non-"msr" REPO_ID, the script must issue a
// DELETE /rest/repositories/<id> before creating, so every `make test-repo`
// run starts from a clean repo.
func TestEnsureRepo_ResetDropsNonMsrRepoBeforeCreate(t *testing.T) {
	root := repoRoot(t)

	var createCalls, deleteCalls int32
	srv := newRepoDouble(t, "msr-test", false, shaclEnabledConfigDouble, &createCalls, &deleteCalls)
	defer srv.Close()

	err, out := runEnsureRepo(t, root, srv.URL, "REPO_ID=msr-test", "REPO_RESET=1")
	if err != nil {
		t.Fatalf("ensure-repo.sh failed with REPO_ID=msr-test REPO_RESET=1: %v\noutput:\n%s", err, out)
	}
	if got := atomic.LoadInt32(&deleteCalls); got != 1 {
		t.Errorf("ensure-repo.sh issued %d DELETE(s) for REPO_RESET=1, want exactly 1", got)
	}
	if got := atomic.LoadInt32(&createCalls); got != 1 {
		t.Errorf("ensure-repo.sh issued %d create POST(s) after reset, want 1", got)
	}
}

// TestEnsureRepo_ResetRefusesMsr pins design D4's hard guard: REPO_ID=msr
// together with REPO_RESET=1 must be refused (non-zero exit, no DELETE
// issued) so this flag can never drop the real production repository.
func TestEnsureRepo_ResetRefusesMsr(t *testing.T) {
	root := repoRoot(t)

	var createCalls, deleteCalls int32
	srv := newRepoDouble(t, "msr", true, shaclEnabledConfigDouble, &createCalls, &deleteCalls)
	defer srv.Close()

	err, out := runEnsureRepo(t, root, srv.URL, "REPO_ID=msr", "REPO_RESET=1")
	if err == nil {
		t.Fatalf("expected scripts/ensure-repo.sh to refuse REPO_ID=msr with REPO_RESET=1, but it succeeded; output:\n%s", out)
	}
	if got := atomic.LoadInt32(&deleteCalls); got != 0 {
		t.Errorf("ensure-repo.sh issued %d DELETE(s) despite the REPO_ID=msr guard, want 0 (must never drop msr)", got)
	}
	lower := strings.ToLower(out)
	if !strings.Contains(lower, "msr") {
		t.Errorf("expected refusal output to mention 'msr', got:\n%s", out)
	}
}
