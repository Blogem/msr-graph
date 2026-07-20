package scripts

// Test for task 7.7 / design D7 ("ensure-repo.sh detects and warns on a
// non-SHACL existing repo"). scripts/ensure-repo.sh is a forbidden path
// for this change (read-only) and, as of this test's authoring, hardcodes
// REPO_ID="msr" with no override -- so this test can never safely point
// the real, unmodified script at a throwaway repo id on a live GraphDB
// without risking the real "msr" repository (which the task contract
// explicitly forbids clobbering).
//
// Per the task contract's documented fallback ("if a full live test is
// impractical, at minimum test the script's SHACL-detection logic...
// document what is and isn't exercised"), this test instead runs the
// REAL, unmodified script end-to-end against a fully local
// httptest.Server standing in for GraphDB's REST API. Nothing here EVER
// touches a real GraphDB instance or a real "msr" repository, no matter
// what repo id the script hardcodes -- the "msr" the script sees only
// exists inside this test's in-memory double. Because of that, this test
// does NOT need to be gated behind requireGraphDB/GRAPHDB_REQUIRED (no
// external GraphDB dependency at all): it is a hermetic test that should
// run in any environment with bash + curl available.
//
// What IS exercised:
//   - the idempotent check-then-create path already implemented today
//     (GET /rest/repositories, grep-for-id, no-op on match) --
//     unaffected by task 1.4's D7 addition, so
//     TestEnsureRepo_NoOpWhenRepoAlreadyExists is expected to pass
//     immediately, pre- and post-merge.
//   - once task 1.4 lands the D7 detection: the pass/fail branch based on
//     whichever GraphDB endpoint that detection queries for the existing
//     repo's sail config, PROVIDED it queries GET /rest/repositories/<id>
//     or GET /repositories/<id>/config -- design.md documents
//     "GET /rest/repositories/msr or the repository config download" as
//     the two candidates, and this double serves both routes.
//
// What is NOT exercised:
//   - real GraphDB wire behavior/response shape for the config-inspection
//     call (this is a double, not a live round-trip);
//   - the real repo-creation POST's interaction with an actual
//     SHACL-enabled config;
//   - if task 1.4 queries neither candidate endpoint, this double's
//     routes will need updating in pass 2 -- flagged explicitly in the
//     tester's handoff report rather than guessed at silently.

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
// its exit error (nil on success) and combined stdout+stderr.
func runEnsureRepo(t *testing.T, root, baseURL string) (error, string) {
	t.Helper()
	cmd := exec.Command(ensureRepoScriptPath(t, root))
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "GRAPHDB_URL="+baseURL)
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
