package graph_test

// Shared helpers for the SHACL-validation integration tests (7.1-7.7,
// 7.10) added by the shacl-validation change (P3.5 chunk 13). All
// urn:msr:data fixture triples built via these helpers deliberately carry
// prov:wasDerivedFrom + prov:wasGeneratedBy (and every other predicate a
// real writer emits), per design.md's risk note: "Integration fixtures
// asserting acceptance of valid data must include the PROV edges the
// writers now emit." Subjects are minted with a per-call unique suffix
// (uniqueLocal) so repeated runs against a shared, persistent GraphDB
// instance never collide with a prior run's leftover fixtures.
//
// These tests assert SHACL shape *behavior* (reject vs. accept) via plain
// err != nil / err == nil checks on graph.Client.Update, NOT via
// graph.ValidationError -- that type (design D5, task 5.1) is exercised
// specifically by validation_error_test.go (task 7.9), a pure unit test
// using an httptest double. Keeping shape-behavior assertions decoupled
// from error-*classification* correctness means a shape regression and an
// error-typing regression surface as distinct test failures instead of
// being conflated. It also means this file -- and every
// shacl_*_integration_test.go file that only uses these helpers -- has no
// compile-time dependency on graph.ValidationError, so they compile
// independent of whether task 5.1 has landed yet.
//
// repoRoot (module-root locator) is already defined in
// seed_integration_test.go and reused as-is by files in this change that
// need it (e.g. shacl_unit_allowlist_integration_test.go,
// shacl_shapes_load_integration_test.go).

import (
	"context"
	"fmt"
	"sync/atomic"
	"testing"
	"time"

	"github.com/blogem/msr-graph/internal/graph"
)

// shaclPrefixes are the PREFIX declarations every SHACL fixture update
// uses, matching ontology/msr.ttl's own @prefix bindings.
const shaclPrefixes = `
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX unit: <http://qudt.org/vocab/unit/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
`

// shaclFixtureCounter guarantees fixture-subject uniqueness even for two
// calls to uniqueLocal landing in the same wall-clock nanosecond.
var shaclFixtureCounter int64

// uniqueLocal returns a fixture-local-name fragment ("<label>-<ts>-<n>")
// guaranteed unique across this test run, so fixture subjects never
// collide with a prior run's leftovers on a shared, persistent GraphDB.
func uniqueLocal(label string) string {
	n := atomic.AddInt64(&shaclFixtureCounter, 1)
	return fmt.Sprintf("%s-%d-%d", label, time.Now().UnixNano(), n)
}

// insertData runs an INSERT DATA update against GRAPH <urn:msr:data> with
// the shared SHACL-fixture prefixes in scope, returning Update's error
// unchanged (nil on success, non-nil -- including a SHACL rejection -- on
// failure).
func insertData(t *testing.T, client *graph.Client, triples string) error {
	t.Helper()
	update := shaclPrefixes + fmt.Sprintf("INSERT DATA { GRAPH <%s> {\n%s\n} }", graph.Data, triples)
	return client.Update(context.Background(), update)
}

// deleteData is the DELETE DATA counterpart to insertData, used from
// t.Cleanup to remove an accept-case fixture's triples after the test so
// urn:msr:data does not accumulate SHACL test fixtures indefinitely across
// runs. Best-effort: a cleanup failure is logged, not fatal (the fixture's
// unique subject means a failed cleanup cannot corrupt a later test).
func deleteData(t *testing.T, client *graph.Client, triples string) {
	t.Helper()
	update := shaclPrefixes + fmt.Sprintf("DELETE DATA { GRAPH <%s> {\n%s\n} }", graph.Data, triples)
	if err := client.Update(context.Background(), update); err != nil {
		t.Logf("cleanup: deleting SHACL fixture triples: %v", err)
	}
}

// assertRejected fails the test unless err is non-nil, per every shape
// requirement's "the commit is rejected" scenario.
func assertRejected(t *testing.T, err error, context string) {
	t.Helper()
	if err == nil {
		t.Fatalf("%s: expected the write to be rejected by SHACL, got no error", context)
	}
}

// assertAccepted fails the test unless err is nil, per every shape
// requirement's "the commit succeeds" scenario.
func assertAccepted(t *testing.T, err error, context string) {
	t.Helper()
	if err != nil {
		t.Fatalf("%s: expected the write to be accepted, got error: %v", context, err)
	}
}
