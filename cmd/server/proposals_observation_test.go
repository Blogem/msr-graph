package main

// Unit tests for the proposal-observation-provenance aggregation
// requirements (openspec/changes/proposal-observation-provenance, specs
// change-proposal-schema + proposal-review-api, tasks 5.1/5.2/7.4/7.5):
// the queue endpoint SHALL aggregate a proposal's msr:hasObservation nodes
// into exactly one row per proposal id (documentFrequency/totalOccurrences/
// corpusCount/corpora, with the latest occurrenceCount per document), and
// the detail endpoint SHALL return an observation breakdown grouped by
// corpus/document.
//
// Because this pass runs in parallel with the coder's handler rewrite
// (proposals.go tasks 5.1/5.2), the exact SPARQL variable names the
// rewritten queue/detail queries select are not yet known. Following this
// package's existing pass-1 convention (see proposals_test.go's own
// doc-comment), canned bindings below hedge across the most plausible
// variable-naming choices for the observation-shaped columns
// (document/documentId/inDocument, corpus/inCorpus, occurrenceCount/count,
// generatedAtTime/observedAt) so the tests exercise real handler
// aggregation behavior rather than an accidental naming coincidence. See
// the handoff report for the exact aliases used, for reconciliation in
// pass 2.
//
// ASSUMPTION (pass-1, flagged for reconciliation): the fixture below
// simulates a SPARQL result shape where the queue query returns one row
// per (proposal, document, corpus) triple with a per-row occurrenceCount/
// generatedAtTime (i.e. NOT fully pre-aggregated into a single row via
// GROUP_CONCAT) -- this is deliberately the least-aggregated plausible
// shape, so that the test proves the HANDLER (not just the SPARQL query
// text) is responsible for collapsing multiple observation rows into one
// queue entry per proposal id, per the proposal-review-api spec's "The
// query SHALL aggregate ... so a proposal ... never produces more than
// one row" (an "e.g." SPARQL-side suggestion, not the literal requirement
// -- the requirement is behavioral).

import (
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
)

const (
	corpusChemistryIRI = "https://w3id.org/msr-kg/data#corpus-chemistry"
	corpusSafetyIRI    = "https://w3id.org/msr-kg/data#corpus-safety"
)

// obsRow builds one canned observation-shaped binding row, hedging across
// plausible column-name aliases for the proposal identifier, the document,
// the corpus, the per-document occurrence count, and the observation
// timestamp.
func obsRow(proposalID, kind, status, term, document, corpus string, occurrenceCount int, generatedAt string) map[string]graph.Binding {
	full := "https://w3id.org/msr-kg/data#proposal-" + proposalID
	freq := strconv.Itoa(occurrenceCount)
	return map[string]graph.Binding{
		"id":              {Type: "literal", Value: proposalID},
		"proposal":        {Type: "uri", Value: full},
		"s":               {Type: "uri", Value: full},
		"kind":            {Type: "literal", Value: kind},
		"status":          {Type: "literal", Value: status},
		"term":            {Type: "literal", Value: term},
		"document":        {Type: "uri", Value: document},
		"documentId":      {Type: "uri", Value: document},
		"inDocument":      {Type: "uri", Value: document},
		"doc":             {Type: "uri", Value: document},
		"corpus":          {Type: "uri", Value: corpus},
		"inCorpus":        {Type: "uri", Value: corpus},
		"occurrenceCount": {Type: "literal", Value: freq, Datatype: xsdInteger},
		"count":           {Type: "literal", Value: freq, Datatype: xsdInteger},
		"generatedAtTime": {Type: "literal", Value: generatedAt, Datatype: "http://www.w3.org/2001/XMLSchema#dateTime"},
		"observedAt":      {Type: "literal", Value: generatedAt, Datatype: "http://www.w3.org/2001/XMLSchema#dateTime"},
	}
}

// zeroObsRow builds a canned row for a proposal with NO observation rows
// at all (only the base ChangeProposal columns bound) -- the queue's
// requirement "a proposal with zero observation rows still returns one
// row with zeroed aggregates" (spec proposal-review-api, task 5.3).
func zeroObsRow(proposalID, kind, status, term string) map[string]graph.Binding {
	full := "https://w3id.org/msr-kg/data#proposal-" + proposalID
	return map[string]graph.Binding{
		"id":       {Type: "literal", Value: proposalID},
		"proposal": {Type: "uri", Value: full},
		"s":        {Type: "uri", Value: full},
		"kind":     {Type: "literal", Value: kind},
		"status":   {Type: "literal", Value: status},
		"term":     {Type: "literal", Value: term},
	}
}

const (
	obsPropID      = "property-solubility"
	obsPropKind    = "property"
	obsPropStatus  = "pending"
	obsPropTerm    = "solubility"
	obsDocChem     = "https://w3id.org/msr-kg/data#ORNL-TM-2316"
	obsDocSafety   = "https://w3id.org/msr-kg/data#IAEA-SR-1"
	obsRunT1       = "2026-06-01T00:00:00Z"
	obsRunT2Latest = "2026-07-01T00:00:00Z"

	zeroObsID     = "instance-flibe"
	zeroObsKind   = "instance"
	zeroObsStatus = "approved"
	zeroObsTerm   = "FLiBe"
)

// multiCorpusMultiRunObservationRows returns the raw per-observation rows
// for a single proposal ("property-solubility") observed:
//   - once in the chemistry corpus (document ORNL-TM-2316, count 4), and
//   - TWICE in the safety corpus (document IAEA-SR-1): an earlier mining
//     run recorded count 2 at obsRunT1, and a LATER re-mining run recorded
//     count 5 at obsRunT2Latest (append-only: both rows are present in the
//     graph; the "latest observation per document" must win).
//
// Expected aggregates: documentFrequency=2 (distinct documents), corpusCount=2,
// corpora={chemistry, safety}, totalOccurrences=4+5=9 (NOT 4+2+5=11 -- the
// stale safety observation must not be double-counted).
func multiCorpusMultiRunObservationRows() []map[string]graph.Binding {
	return []map[string]graph.Binding{
		obsRow(obsPropID, obsPropKind, obsPropStatus, obsPropTerm, obsDocChem, corpusChemistryIRI, 4, obsRunT1),
		obsRow(obsPropID, obsPropKind, obsPropStatus, obsPropTerm, obsDocSafety, corpusSafetyIRI, 2, obsRunT1),
		obsRow(obsPropID, obsPropKind, obsPropStatus, obsPropTerm, obsDocSafety, corpusSafetyIRI, 5, obsRunT2Latest),
		zeroObsRow(zeroObsID, zeroObsKind, zeroObsStatus, zeroObsTerm),
	}
}

func queueObservationCanned() *graph.Results {
	r := &graph.Results{}
	r.Results.Bindings = multiCorpusMultiRunObservationRows()
	return r
}

func findProposalEntry(t *testing.T, proposals []any, id string) map[string]any {
	t.Helper()
	for _, raw := range proposals {
		entry, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		if got, _ := entry["id"].(string); got == id {
			return entry
		}
	}
	t.Fatalf("proposal id %q not found in queue response: %#v", id, proposals)
	return nil
}

// --- 7.4: queue collapses multiple observation rows into one row --------

func TestProposalsQueue_CollapsesMultiCorpusMultiRunObservationsIntoOneRow(t *testing.T) {
	reader := &fakeProposalReader{selectRawFn: func(string) (*graph.Results, error) {
		return queueObservationCanned(), nil
	}}
	mux, _ := newTestMux(reader, &fakeProposalService{}, &fakeCheckpointService{})

	req := httptest.NewRequest(http.MethodGet, "/api/proposals", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
	}

	body := decodeJSONObject(t, rec.Body.Bytes())
	proposals := asSlice(t, body["proposals"], "proposals")

	// Exactly one row for obsPropID despite 3 raw observation rows spanning
	// 2 corpora and 2 mining runs for the same document.
	count := 0
	for _, raw := range proposals {
		entry, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		if id, _ := entry["id"].(string); id == obsPropID {
			count++
		}
	}
	if count != 1 {
		t.Fatalf("proposal id %q appears %d times in queue response, want exactly 1 (body: %s)",
			obsPropID, count, rec.Body.String())
	}

	entry := findProposalEntry(t, proposals, obsPropID)

	if got := numString(entry["documentFrequency"]); got != "2" {
		t.Errorf("documentFrequency = %v, want 2 (distinct documents)", entry["documentFrequency"])
	}
	if got := numString(entry["totalOccurrences"]); got != "9" {
		t.Errorf("totalOccurrences = %v, want 9 (4 + latest-of-safety-doc:5, not 4+2+5=11)", entry["totalOccurrences"])
	}
	if got := numString(entry["corpusCount"]); got != "2" {
		t.Errorf("corpusCount = %v, want 2", entry["corpusCount"])
	}

	corporaRaw, ok := entry["corpora"]
	if !ok {
		t.Fatalf("response missing \"corpora\" field (entry: %#v)", entry)
	}
	corporaList := asSlice(t, corporaRaw, "corpora")
	if len(corporaList) != 2 {
		t.Fatalf("corpora = %#v, want 2 entries", corporaList)
	}
	seen := map[string]bool{}
	for _, c := range corporaList {
		if s, ok := c.(string); ok {
			seen[s] = true
		}
	}
	if !seen[corpusChemistryIRI] && !seen["corpus-chemistry"] && !containsSubstringAny(corporaList, "chemistry") {
		t.Errorf("corpora %#v does not identify the chemistry corpus", corporaList)
	}
	if !seen[corpusSafetyIRI] && !seen["corpus-safety"] && !containsSubstringAny(corporaList, "safety") {
		t.Errorf("corpora %#v does not identify the safety corpus", corporaList)
	}
}

func containsSubstringAny(items []any, substr string) bool {
	for _, item := range items {
		if s, ok := item.(string); ok && strings.Contains(s, substr) {
			return true
		}
	}
	return false
}

// --- 7.4: a proposal with zero observation rows still returns one row ---

func TestProposalsQueue_ZeroObservationProposalReturnsZeroedAggregates(t *testing.T) {
	reader := &fakeProposalReader{selectRawFn: func(string) (*graph.Results, error) {
		return queueObservationCanned(), nil
	}}
	mux, _ := newTestMux(reader, &fakeProposalService{}, &fakeCheckpointService{})

	req := httptest.NewRequest(http.MethodGet, "/api/proposals", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
	}

	body := decodeJSONObject(t, rec.Body.Bytes())
	proposals := asSlice(t, body["proposals"], "proposals")
	entry := findProposalEntry(t, proposals, zeroObsID)

	if got := numString(entry["documentFrequency"]); got != "0" && got != "" {
		t.Errorf("documentFrequency = %v, want 0 for a proposal with no observations", entry["documentFrequency"])
	}
	if got := numString(entry["totalOccurrences"]); got != "0" && got != "" {
		t.Errorf("totalOccurrences = %v, want 0 for a proposal with no observations", entry["totalOccurrences"])
	}
	if got := numString(entry["corpusCount"]); got != "0" && got != "" {
		t.Errorf("corpusCount = %v, want 0 for a proposal with no observations", entry["corpusCount"])
	}
}

// --- 7.5: detail returns an observation breakdown grouped by corpus/doc -

// newDetailObservationReader dispatches SelectRaw by query text like
// newDetailReader (proposals_test.go), plus a branch for the new
// observation-breakdown query -- detected by the presence of any of the
// ontology predicate names the observation model introduces
// (msr:inDocument / msr:occurrenceCount / msr:hasObservation), checked
// BEFORE the generic evidence catch-all (detailKnownID substring) since an
// observation query naturally also mentions the known proposal id/IRI.
func newDetailObservationReader() *fakeProposalReader {
	return &fakeProposalReader{
		selectRawFn: func(query string) (*graph.Results, error) {
			switch {
			case strings.Contains(query, detailUnknownID):
				return &graph.Results{}, nil
			case strings.Contains(query, "urn:msr:proposal/"+detailKnownID):
				return detailTriplesCanned(), nil
			case strings.Contains(query, "FILTER(?g IN"):
				return detailNeighborhoodCanned(), nil
			case strings.Contains(query, "inDocument") ||
				strings.Contains(query, "occurrenceCount") ||
				strings.Contains(query, "hasObservation"):
				return detailObservationBreakdownCanned(), nil
			case strings.Contains(query, detailKnownID):
				return detailEvidenceCanned(), nil
			default:
				return &graph.Results{}, nil
			}
		},
	}
}

// detailObservationBreakdownCanned returns 2 raw observation rows for the
// known detail proposal, spanning 2 documents in 2 corpora, so the detail
// endpoint's grouped breakdown can be asserted against known values.
func detailObservationBreakdownCanned() *graph.Results {
	r := &graph.Results{}
	r.Results.Bindings = []map[string]graph.Binding{
		obsRow(detailKnownID, "property", "pending", "solubility", obsDocChem, corpusChemistryIRI, 4, obsRunT1),
		obsRow(detailKnownID, "property", "pending", "solubility", obsDocSafety, corpusSafetyIRI, 5, obsRunT2Latest),
	}
	return r
}

func TestProposalDetail_ReturnsObservationBreakdownGroupedByCorpusAndDocument(t *testing.T) {
	reader := newDetailObservationReader()
	mux, _ := newTestMux(reader, &fakeProposalService{}, &fakeCheckpointService{})

	req := httptest.NewRequest(http.MethodGet, "/api/proposals/"+detailKnownID, nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
	}

	raw := rec.Body.String()
	body := decodeJSONObject(t, rec.Body.Bytes())

	obsField, ok := body["observations"]
	if !ok {
		t.Fatalf("detail response missing \"observations\" key (body: %s)", raw)
	}
	groups := asSlice(t, obsField, "observations")
	if len(groups) == 0 {
		t.Fatalf("observations breakdown is empty, want at least one corpus group (body: %s)", raw)
	}

	// The response must mention both corpora and both documents/counts
	// somewhere in the observation breakdown, however the exact per-corpus
	// grouping is shaped by the handler.
	for _, want := range []string{
		"ORNL-TM-2316",
		"IAEA-SR-1",
		"corpus-chemistry",
		"corpus-safety",
	} {
		if !strings.Contains(raw, want) {
			t.Errorf("observation breakdown missing expected reference %q (body: %s)", want, raw)
		}
	}

	// The safety document's latest occurrence count (5, from the later
	// mining run) must be present; the stale earlier-run count for a
	// DIFFERENT document (2, in the multi-run queue fixture) is irrelevant
	// here since this fixture only ever recorded 4 and 5.
	if !strings.Contains(raw, "\"occurrenceCount\":4") && !strings.Contains(raw, "\"occurrenceCount\": 4") &&
		!strings.Contains(raw, "\"count\":4") {
		t.Errorf("observation breakdown missing the chemistry document's occurrence count 4 (body: %s)", raw)
	}
	if !strings.Contains(raw, "\"occurrenceCount\":5") && !strings.Contains(raw, "\"occurrenceCount\": 5") &&
		!strings.Contains(raw, "\"count\":5") {
		t.Errorf("observation breakdown missing the safety document's occurrence count 5 (body: %s)", raw)
	}
}

// Compile-time sanity: ensure graphReader is still satisfied by our fake
// (pins the interface hasn't grown a method this test doesn't know about).
var _ graphReader = (*fakeProposalReader)(nil)
