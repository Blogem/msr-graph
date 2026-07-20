package agent_test

// Tests for the KG-schema prompt builder and version cache (tasks 3.1,
// 3.2, 6.7). fakeSchemaSource routes canned bindings to Select calls by
// recognizing which of the builder's schema-only queries was issued, so
// these tests never contact GraphDB and can freely reorder bindings to
// prove the builder's output does not depend on SPARQL result order.

import (
	"context"
	"strings"
	"sync"
	"testing"

	"github.com/blogem/msr-graph/internal/agent"
	"github.com/blogem/msr-graph/internal/graph"
)

// queryKind classifies a query issued by the prompt builder by matching
// a substring unique to one of its known queries. "unknown" means the
// query didn't match any recognized schema-only query shape -- used to
// assert the builder never issues anything else (e.g. a
// PropertyMeasurement query).
func queryKind(query string) string {
	switch {
	case strings.Contains(query, "owl:versionInfo ?version"):
		return "version"
	case strings.Contains(query, "?class a owl:Class"):
		return "classes"
	case strings.Contains(query, "owl:ObjectProperty"):
		return "properties"
	case strings.Contains(query, "skos:altLabel ?altLabel"):
		return "altLabels"
	case strings.Contains(query, "skos:prefLabel ?prefLabel"):
		return "prefLabels"
	case strings.Contains(query, "msr:hasConstituent"):
		return "constituents"
	case strings.Contains(query, "?salt a msr:MoltenSalt"):
		return "salts"
	case strings.Contains(query, "msr:PropertyMeasurement"):
		return "measurements"
	default:
		return "unknown"
	}
}

// fakeSchemaSource is a fake agent.SchemaSource that returns canned rows
// per query kind and counts how many times each kind was requested, so
// tests can assert both content and call counts (e.g. "the classes query
// ran exactly once across two cache hits").
type fakeSchemaSource struct {
	mu      sync.Mutex
	rows    map[string][]map[string]graph.Binding
	counts  map[string]int
	version string
}

func newFakeSchemaSource() *fakeSchemaSource {
	return &fakeSchemaSource{
		rows:   make(map[string][]map[string]graph.Binding),
		counts: make(map[string]int),
	}
}

func (f *fakeSchemaSource) Select(_ context.Context, query string) (*graph.Results, error) {
	kind := queryKind(query)

	f.mu.Lock()
	f.counts[kind]++
	f.mu.Unlock()

	res := &graph.Results{}
	if kind == "version" {
		res.Results.Bindings = []map[string]graph.Binding{
			{"version": lit(f.version)},
		}
		return res, nil
	}
	res.Results.Bindings = f.rows[kind]
	return res, nil
}

func (f *fakeSchemaSource) callCount(kind string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.counts[kind]
}

func lit(v string) graph.Binding { return graph.Binding{Type: "literal", Value: v} }
func iri(v string) graph.Binding { return graph.Binding{Type: "uri", Value: v} }

// reversed returns a new slice with rows in reverse order, used to prove
// the builder's output does not depend on SPARQL binding order.
func reversed(rows []map[string]graph.Binding) []map[string]graph.Binding {
	out := make([]map[string]graph.Binding, len(rows))
	for i, r := range rows {
		out[len(rows)-1-i] = r
	}
	return out
}

// seedFixture populates f with a small, representative slice of the
// real ontology/vocab/catalog shape (classes, properties, SKOS concepts,
// a salt with two constituents) plus a "measurements" route carrying a
// sentinel coefficient value that must never reach the prompt, since the
// builder must never issue a query the "measurements" kind would match.
func seedFixture(f *fakeSchemaSource, version string) {
	f.version = version

	f.rows["classes"] = []map[string]graph.Binding{
		{"class": iri("https://w3id.org/msr-kg/ontology#MoltenSalt"),
			"label": lit("MoltenSalt"), "comment": lit("A molten-salt melt at a defined composition.")},
		{"class": iri("https://w3id.org/msr-kg/ontology#ChemicalCompound"),
			"comment": lit("A pure chemical compound, e.g. LiF, BeF2.")},
		{"class": iri("https://w3id.org/msr-kg/ontology#Substance")},
	}

	f.rows["properties"] = []map[string]graph.Binding{
		{"property": iri("https://w3id.org/msr-kg/ontology#hasConstituent"), "kind": lit("ObjectProperty"),
			"domain": iri("https://w3id.org/msr-kg/ontology#MoltenSalt"), "range": iri("https://w3id.org/msr-kg/ontology#Constituent")},
		{"property": iri("https://w3id.org/msr-kg/ontology#moleFraction"), "kind": lit("DatatypeProperty"),
			"domain": iri("https://w3id.org/msr-kg/ontology#Constituent"), "range": iri("http://www.w3.org/2001/XMLSchema#decimal")},
	}

	f.rows["prefLabels"] = []map[string]graph.Binding{
		{"concept": iri("https://w3id.org/msr-kg/vocab#flibe"), "prefLabel": lit("FLiBe")},
		{"concept": iri("https://w3id.org/msr-kg/vocab#molten-salts"), "prefLabel": lit("molten salts")},
	}
	f.rows["altLabels"] = []map[string]graph.Binding{
		{"concept": iri("https://w3id.org/msr-kg/vocab#flibe"), "altLabel": lit("LiF-BeF2 eutectic")},
		{"concept": iri("https://w3id.org/msr-kg/vocab#flibe"), "altLabel": lit("LiF-BeF2")},
		{"concept": iri("https://w3id.org/msr-kg/vocab#molten-salts"), "altLabel": lit("fused salts")},
	}

	f.rows["salts"] = []map[string]graph.Binding{
		{"salt": iri("https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"),
			"label": lit("BeF2-LiF (34.0-66.0 mol%)")},
	}
	f.rows["constituents"] = []map[string]graph.Binding{
		{"salt": iri("https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"),
			"compound": iri("https://w3id.org/msr-kg/data#LiF"), "compoundLabel": lit("LiF"), "moleFraction": lit("0.66")},
		{"salt": iri("https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"),
			"compound": iri("https://w3id.org/msr-kg/data#BeF2"), "compoundLabel": lit("BeF2"), "moleFraction": lit("0.34")},
	}

	// A route the builder must never hit: if it did, this sentinel
	// coefficient value would leak into a schema-only prompt.
	f.rows["measurements"] = []map[string]graph.Binding{
		{"measurement": iri("https://w3id.org/msr-kg/data#m-nist-srd27-density-BeF2-LiF-34.0-66.0"),
			"coefficient": lit("2.413")},
	}
}

func TestBuildSchemaPrompt_ByteStableRegardlessOfBindingOrder(t *testing.T) {
	ctx := context.Background()

	f1 := newFakeSchemaSource()
	seedFixture(f1, "0.1.0-seed")
	prompt1, err := agent.BuildSchemaPrompt(ctx, f1)
	if err != nil {
		t.Fatalf("BuildSchemaPrompt: %v", err)
	}

	f2 := newFakeSchemaSource()
	seedFixture(f2, "0.1.0-seed")
	prompt2, err := agent.BuildSchemaPrompt(ctx, f2)
	if err != nil {
		t.Fatalf("BuildSchemaPrompt: %v", err)
	}

	if prompt1 != prompt2 {
		t.Fatalf("BuildSchemaPrompt is not deterministic across two identical fixtures:\n--- prompt1 ---\n%s\n--- prompt2 ---\n%s", prompt1, prompt2)
	}

	// Now shuffle every multi-row binding set and rebuild: the output
	// must still be byte-identical, proving the builder sorts rather
	// than relying on SPARQL result order.
	f3 := newFakeSchemaSource()
	seedFixture(f3, "0.1.0-seed")
	for kind, rows := range f3.rows {
		f3.rows[kind] = reversed(rows)
	}
	prompt3, err := agent.BuildSchemaPrompt(ctx, f3)
	if err != nil {
		t.Fatalf("BuildSchemaPrompt: %v", err)
	}

	if prompt1 != prompt3 {
		t.Fatalf("BuildSchemaPrompt output depends on binding order:\n--- original order ---\n%s\n--- reversed order ---\n%s", prompt1, prompt3)
	}
}

func TestBuildSchemaPrompt_InstanceDataAbsent(t *testing.T) {
	ctx := context.Background()

	f := newFakeSchemaSource()
	seedFixture(f, "0.1.0-seed")

	prompt, err := agent.BuildSchemaPrompt(ctx, f)
	if err != nil {
		t.Fatalf("BuildSchemaPrompt: %v", err)
	}

	// Schema-level markers must be present.
	for _, want := range []string{
		"https://w3id.org/msr-kg/ontology#MoltenSalt",          // class
		"https://w3id.org/msr-kg/ontology#hasConstituent",      // property
		"https://w3id.org/msr-kg/vocab#flibe",                  // SKOS concept
		"FLiBe",                                                // prefLabel
		"LiF-BeF2",                                             // altLabel
		"https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0", // salt catalog entry
	} {
		if !strings.Contains(prompt, want) {
			t.Errorf("prompt missing schema marker %q\nprompt:\n%s", want, prompt)
		}
	}

	// Instance-level content must be absent: the sentinel coefficient
	// value and the measurement instance IRI it hangs off of. (A schema
	// class name like msr:PropertyMeasurement is legitimate schema-level
	// vocabulary and may appear in guidance prose or, against the real
	// ontology, in the classes section itself -- it is the coefficient
	// value and measurement-row instance data that must never appear.)
	for _, unwanted := range []string{"2.413", "m-nist-srd27-density-BeF2-LiF-34.0-66.0"} {
		if strings.Contains(prompt, unwanted) {
			t.Errorf("prompt leaked instance-level content %q\nprompt:\n%s", unwanted, prompt)
		}
	}

	// The builder must never have issued a query this fake would route
	// to the measurements fixture in the first place -- the structural
	// guarantee behind the content check above: it isn't just that the
	// sentinel value happens not to appear, the builder never asks.
	if n := f.callCount("measurements"); n != 0 {
		t.Errorf("builder issued %d queries matching msr:PropertyMeasurement; want 0", n)
	}
	if n := f.callCount("unknown"); n != 0 {
		t.Errorf("builder issued %d unrecognized queries; want 0", n)
	}
}

func TestBuildSchemaPrompt_HeaderDescribesLinksToGroundingNotCloseMatch(t *testing.T) {
	ctx := context.Background()

	f := newFakeSchemaSource()
	seedFixture(f, "0.1.0-seed")

	prompt, err := agent.BuildSchemaPrompt(ctx, f)
	if err != nil {
		t.Fatalf("BuildSchemaPrompt: %v", err)
	}

	// D2/D3: the header must describe grounding a salt via a real
	// msr:Mention's surfaceForm, following msr:linksTo to the
	// msr:MoltenSalt individual, with msr:inDocument as the traceable
	// evidence -- the twin of sparql.go's tool-description regression
	// guard (TestSPARQLTool_SpecDescribesGroundingAndForbidsFrom).
	for _, want := range []string{"msr:linksTo", "msr:inDocument"} {
		if !strings.Contains(prompt, want) {
			t.Errorf("prompt header missing %q\nprompt:\n%s", want, prompt)
		}
	}

	// D2/D6: skos:closeMatch is a SKOS range abuse (its domain/range is
	// skos:Concept; neither a MoltenSalt individual nor a
	// PhysicalProperty term is one) and must not appear anywhere in the
	// grounding guidance.
	if strings.Contains(strings.ToLower(prompt), "closematch") {
		t.Errorf("prompt header reintroduced skos:closeMatch grounding; got: %s", prompt)
	}
}

func TestPromptCache_ReusesUntilVersionBump(t *testing.T) {
	ctx := context.Background()

	f := newFakeSchemaSource()
	seedFixture(f, "v1")

	cache := agent.NewPromptCache(f)

	prompt1, version1, err := cache.Get(ctx)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if version1 != "v1" {
		t.Fatalf("version = %q, want v1", version1)
	}

	prompt2, version2, err := cache.Get(ctx)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if version2 != "v1" {
		t.Fatalf("version = %q, want v1", version2)
	}
	if prompt1 != prompt2 {
		t.Fatalf("cached prompt changed between calls with an unchanged version")
	}

	// The version SELECT runs every call, but the schema-fetching
	// queries must only have run once: the second Get reused the cache.
	if n := f.callCount("version"); n != 2 {
		t.Fatalf("version query ran %d times, want 2", n)
	}
	if n := f.callCount("classes"); n != 1 {
		t.Fatalf("classes query ran %d times across two unchanged-version Gets, want 1 (no rebuild)", n)
	}

	// Bump the version -- simulating a real schema change (e.g. an
	// ontology approval landing a new class), so the rebuilt prompt is
	// expected to differ -- and confirm the next Get rebuilds.
	f.version = "v2"
	f.rows["classes"] = append(f.rows["classes"], map[string]graph.Binding{
		"class": iri("https://w3id.org/msr-kg/ontology#NewSeedClass"),
	})
	prompt3, version3, err := cache.Get(ctx)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if version3 != "v2" {
		t.Fatalf("version = %q, want v2", version3)
	}
	if prompt3 == prompt2 {
		t.Fatalf("prompt did not change after a version bump")
	}
	if n := f.callCount("classes"); n != 2 {
		t.Fatalf("classes query ran %d times after a version bump, want 2 (one rebuild)", n)
	}
}

func TestDetectVersion(t *testing.T) {
	ctx := context.Background()

	f := newFakeSchemaSource()
	seedFixture(f, "0.1.0-seed")

	got, err := agent.DetectVersion(ctx, f)
	if err != nil {
		t.Fatalf("DetectVersion: %v", err)
	}
	if got != "0.1.0-seed" {
		t.Fatalf("DetectVersion = %q, want 0.1.0-seed", got)
	}
}
