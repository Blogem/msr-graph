// Proposal review HTTP API (openspec/changes/apply-ontology-changes,
// spec proposal-review-api): the JSON queue/detail/disposition endpoints
// the review UI (chunk 10) consumes to serve the change-proposal queue,
// render a proposal as a diff, edit it, and dispose of it. Every read
// here goes through the staging-inclusive path (SelectRaw with an
// explicit GRAPH scope), never the core-dataset Select, so pending
// proposals stay invisible to the analysis agent's dataset while visible
// to reviewers. The disposition semantics themselves (routing, version
// bump, provenance) live in internal/proposal; these handlers stay thin
// (design D6) and only shape SPARQL results into JSON / JSON requests
// into engine calls.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"strings"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/proposal"
)

// Namespaces used to build the msr:ChangeProposal resource and evidence
// queries below (chunk-8 proposal schema). These match the PREFIX
// declarations internal/proposal's sparqlPrefixes uses, so a proposal's
// own CURIEs resolve the same way here.
const (
	msrNS  = "https://w3id.org/msr-kg/ontology#"
	msrdNS = "https://w3id.org/msr-kg/data#"
)

// proposalIDPattern is the conservative charset a proposal {id} path
// segment must match: chunk 8's deterministic "{kind}-{term-slug}"
// segment (e.g. "property-solubility") is ASCII letters, digits,
// dashes, and underscores. Every handler below validates the path
// value against this pattern before embedding it in a SPARQL query
// string, so a malformed/hostile path segment can never break out of
// the generated query -- it is treated identically to an unknown id
// (404), since neither case has a matching msr:ChangeProposal resource.
var proposalIDPattern = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

// graphReader is the staging-inclusive read subset of *graph.Client the
// queue and detail handlers use. Declaring it here (rather than
// depending on *graph.Client directly) lets both handlers be unit-tested
// against a fake with no live GraphDB (design D6).
type graphReader interface {
	SelectRaw(ctx context.Context, query string) (*graph.Results, error)
}

// proposalService is the disposition subset of *proposal.Engine the
// edit/approve/reject handlers use.
type proposalService interface {
	Approve(ctx context.Context, id string, req proposal.ApproveRequest) error
	Reject(ctx context.Context, id string) error
	Edit(ctx context.Context, id string, triples string) error
}

// proposalQueueResponse is the GET /api/proposals response shape.
type proposalQueueResponse struct {
	Proposals []proposalSummary `json:"proposals"`
}

// proposalSummary is one row of the queue listing.
type proposalSummary struct {
	ID           string `json:"id"`
	Kind         string `json:"kind"`
	Status       string `json:"status"`
	Term         string `json:"term"`
	DocFrequency int    `json:"docFrequency"`
}

// proposalQueueQuery reads every msr:ChangeProposal resource from
// urn:msr:staging. It is a fixed query string (no request-derived
// values embedded), so it carries no injection surface; the optional
// ?status filter is applied to the results in Go instead of by
// interpolating the query, keeping this string static.
const proposalQueueQuery = `PREFIX msr: <https://w3id.org/msr-kg/ontology#>
SELECT ?s ?kind ?status ?term ?docFrequency WHERE {
  GRAPH <urn:msr:staging> {
    ?s a msr:ChangeProposal ;
       msr:kind ?kind ;
       msr:reviewStatus ?status ;
       msr:term ?term ;
       msr:docFrequency ?docFrequency .
  }
}`

// newProposalQueueHandler builds the GET /api/proposals handler: it
// lists the msr:ChangeProposal resources staged in urn:msr:staging,
// optionally filtered to a single review status by the ?status query
// parameter (spec "Queue endpoint lists proposals filtered by review
// status").
func newProposalQueueHandler(gr graphReader) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		statusFilter := r.URL.Query().Get("status")

		results, err := gr.SelectRaw(r.Context(), proposalQueueQuery)
		if err != nil {
			mapEngineError(w, err)
			return
		}

		proposals := make([]proposalSummary, 0, len(results.Results.Bindings))
		for _, b := range results.Results.Bindings {
			id, ok := proposalIDFromResourceIRI(b["s"].Value)
			if !ok {
				// Not a msrd:proposal-{id} resource in the expected shape;
				// skip rather than fail the whole listing.
				continue
			}
			status := b["status"].Value
			if statusFilter != "" && status != statusFilter {
				continue
			}
			docFreq, _ := strconv.Atoi(b["docFrequency"].Value)
			proposals = append(proposals, proposalSummary{
				ID:           id,
				Kind:         b["kind"].Value,
				Status:       status,
				Term:         b["term"].Value,
				DocFrequency: docFreq,
			})
		}

		writeJSON(w, http.StatusOK, proposalQueueResponse{Proposals: proposals})
	}
}

// proposalDetailResponse is the GET /api/proposals/{id} response shape
// (spec "Detail endpoint returns triples, evidence, and affected
// neighborhood"; design D7).
type proposalDetailResponse struct {
	ID           string           `json:"id"`
	Triples      []tripleJSON     `json:"triples"`
	Evidence     []evidenceJSON   `json:"evidence"`
	Neighborhood []neighborTriple `json:"neighborhood"`
}

// tripleJSON is one triple from the proposal's urn:msr:proposal/{id}
// graph.
type tripleJSON struct {
	Subject    string `json:"subject"`
	Predicate  string `json:"predicate"`
	Object     string `json:"object"`
	ObjectType string `json:"objectType"`
	Datatype   string `json:"datatype,omitempty"`
	Lang       string `json:"lang,omitempty"`
}

// evidenceJSON is one msr:Evidence node cited by the proposal.
type evidenceJSON struct {
	Text        string `json:"text"`
	CitedIn     string `json:"citedIn"`
	StartOffset int    `json:"startOffset"`
	EndOffset   int    `json:"endOffset"`
}

// neighborTriple is one core-graph triple about an IRI the proposal
// references -- the bounded one-hop "affected ontology neighborhood"
// (design D7).
type neighborTriple struct {
	Subject   string `json:"subject"`
	Predicate string `json:"predicate"`
	Object    string `json:"object"`
}

// newProposalDetailHandler builds the GET /api/proposals/{id} handler.
func newProposalDetailHandler(gr graphReader) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if !proposalIDPattern.MatchString(id) {
			mapEngineError(w, unknownProposalError(id))
			return
		}

		exists, err := proposalResourceExists(r.Context(), gr, id)
		if err != nil {
			mapEngineError(w, err)
			return
		}
		if !exists {
			mapEngineError(w, unknownProposalError(id))
			return
		}

		triples, err := readProposalTriples(r.Context(), gr, id)
		if err != nil {
			mapEngineError(w, err)
			return
		}

		evidence, err := readProposalEvidence(r.Context(), gr, id)
		if err != nil {
			mapEngineError(w, err)
			return
		}

		neighborhood, err := readProposalNeighborhood(r.Context(), gr, triples)
		if err != nil {
			mapEngineError(w, err)
			return
		}

		writeJSON(w, http.StatusOK, proposalDetailResponse{
			ID:           id,
			Triples:      triples,
			Evidence:     evidence,
			Neighborhood: neighborhood,
		})
	}
}

// unknownProposalError builds the error mapEngineError renders as 404
// for an id with no matching msr:ChangeProposal resource -- whether
// because it never existed or because it failed proposalIDPattern.
func unknownProposalError(id string) error {
	return fmt.Errorf("%w: %q", proposal.ErrNotFound, id)
}

// proposalResourceIRI returns the absolute msrd:proposal-{id} IRI for
// id, matching chunk 8's deterministic resource naming and
// internal/proposal's own proposalResourceIRI.
func proposalResourceIRI(id string) string {
	return msrdNS + "proposal-" + id
}

// proposalResourceIRIPrefix is the fixed prefix stripped by
// proposalIDFromResourceIRI to recover a proposal id from a resource
// IRI returned by a SPARQL query.
const proposalResourceIRIPrefix = msrdNS + "proposal-"

// proposalIDFromResourceIRI derives the "{kind}-{term-slug}" id segment
// from a msrd:proposal-{id} resource IRI, the inverse of
// proposalResourceIRI.
func proposalIDFromResourceIRI(iri string) (string, bool) {
	if !strings.HasPrefix(iri, proposalResourceIRIPrefix) {
		return "", false
	}
	return strings.TrimPrefix(iri, proposalResourceIRIPrefix), true
}

// proposalResourceExists reports whether id has a msr:reviewStatus
// triple on its msrd:proposal-{id} resource in urn:msr:staging -- the
// same existence test internal/proposal's Engine.currentStatus uses
// (lifecycle.go), so the HTTP layer's notion of "unknown proposal"
// matches the engine's.
func proposalResourceExists(ctx context.Context, gr graphReader, id string) (bool, error) {
	query := fmt.Sprintf(`PREFIX msr: <%s>
SELECT ?status WHERE { GRAPH <%s> { <%s> msr:reviewStatus ?status } }`,
		msrNS, graph.Staging, proposalResourceIRI(id))

	results, err := gr.SelectRaw(ctx, query)
	if err != nil {
		return false, fmt.Errorf("proposals: read status for %q: %w", id, err)
	}
	return len(results.Results.Bindings) > 0, nil
}

// readProposalTriples reads every triple in id's urn:msr:proposal/{id}
// graph via SelectRaw with an explicit GRAPH scope (graph.ProposalGraph),
// never the core-dataset Select.
func readProposalTriples(ctx context.Context, gr graphReader, id string) ([]tripleJSON, error) {
	query := fmt.Sprintf(`SELECT ?s ?p ?o WHERE { GRAPH <%s> { ?s ?p ?o } }`,
		graph.ProposalGraph(id))

	results, err := gr.SelectRaw(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("proposals: read triples for %q: %w", id, err)
	}

	triples := make([]tripleJSON, 0, len(results.Results.Bindings))
	for _, b := range results.Results.Bindings {
		o := b["o"]
		triples = append(triples, tripleJSON{
			Subject:    b["s"].Value,
			Predicate:  b["p"].Value,
			Object:     o.Value,
			ObjectType: o.Type,
			Datatype:   o.Datatype,
			Lang:       o.XMLLang,
		})
	}
	return triples, nil
}

// readProposalEvidence reads id's msr:hasEvidence msr:Evidence nodes
// from urn:msr:staging: the cited sentence text, the reused msr:citedIn
// document, and the msr:startOffset/msr:endOffset span (spec "Detail
// endpoint returns triples, evidence, and affected neighborhood").
func readProposalEvidence(ctx context.Context, gr graphReader, id string) ([]evidenceJSON, error) {
	query := fmt.Sprintf(`PREFIX msr: <%s>
SELECT ?text ?citedIn ?startOffset ?endOffset WHERE {
  GRAPH <%s> {
    <%s> msr:hasEvidence ?ev .
    ?ev msr:evidenceText ?text ;
        msr:citedIn ?citedIn ;
        msr:startOffset ?startOffset ;
        msr:endOffset ?endOffset .
  }
}`, msrNS, graph.Staging, proposalResourceIRI(id))

	results, err := gr.SelectRaw(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("proposals: read evidence for %q: %w", id, err)
	}

	evidence := make([]evidenceJSON, 0, len(results.Results.Bindings))
	for _, b := range results.Results.Bindings {
		start, _ := strconv.Atoi(b["startOffset"].Value)
		end, _ := strconv.Atoi(b["endOffset"].Value)
		evidence = append(evidence, evidenceJSON{
			Text:        b["text"].Value,
			CitedIn:     b["citedIn"].Value,
			StartOffset: start,
			EndOffset:   end,
		})
	}
	return evidence, nil
}

// safeIRIRef reports whether s can be embedded inside a SPARQL/Turtle
// IRIREF (<...>) -- no whitespace or any of <>"{}|^`\, mirroring
// internal/proposal's validateIRIRef. readProposalNeighborhood uses it
// to skip any referenced value that is not actually a safe absolute IRI
// before building the FILTER clause below, rather than fail the whole
// detail read over one unusual binding.
func safeIRIRef(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		switch {
		case r <= ' ', r == '<', r == '>', r == '"', r == '{', r == '}', r == '|', r == '^', r == '`', r == '\\':
			return false
		}
	}
	return true
}

// referencedIRIs collects the unique, safe-to-embed IRI values a
// proposal's triples reference -- both subjects and objects typed "uri"
// -- for the one-hop neighborhood lookup (design D7).
func referencedIRIs(triples []tripleJSON) []string {
	seen := make(map[string]bool)
	var iris []string
	add := func(value, typ string) {
		if typ != "uri" || !safeIRIRef(value) || seen[value] {
			return
		}
		seen[value] = true
		iris = append(iris, value)
	}
	for _, t := range triples {
		add(t.Subject, "uri") // subjects are always IRIs in this store
		add(t.Object, t.ObjectType)
	}
	return iris
}

// readProposalNeighborhood reads the bounded one-hop "affected ontology
// neighborhood": core-graph (urn:msr:ontology / urn:msr:data /
// urn:msr:vocab) triples whose subject is one of the IRIs triples
// references (design D7). It is read via SelectRaw with an explicit
// GRAPH FILTER scoped to the three core graphs, not the core-dataset
// Select, so it stays consistent with every other read in this file.
func readProposalNeighborhood(ctx context.Context, gr graphReader, triples []tripleJSON) ([]neighborTriple, error) {
	iris := referencedIRIs(triples)
	if len(iris) == 0 {
		return []neighborTriple{}, nil
	}

	var refs strings.Builder
	for i, iri := range iris {
		if i > 0 {
			refs.WriteString(", ")
		}
		refs.WriteString("<" + iri + ">")
	}

	query := fmt.Sprintf(`SELECT ?s ?p ?o WHERE {
  GRAPH ?g { ?s ?p ?o }
  FILTER(?g IN (<%s>, <%s>, <%s>))
  FILTER(?s IN (%s))
}`, graph.Ontology, graph.Data, graph.Vocab, refs.String())

	results, err := gr.SelectRaw(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("proposals: read neighborhood: %w", err)
	}

	neighborhood := make([]neighborTriple, 0, len(results.Results.Bindings))
	for _, b := range results.Results.Bindings {
		neighborhood = append(neighborhood, neighborTriple{
			Subject:   b["s"].Value,
			Predicate: b["p"].Value,
			Object:    b["o"].Value,
		})
	}
	return neighborhood, nil
}

// proposalEditRequest is the PUT /api/proposals/{id}/graph request body.
type proposalEditRequest struct {
	Triples string `json:"triples"`
}

// newProposalEditHandler builds the PUT /api/proposals/{id}/graph
// handler: it replaces id's proposal graph with the request body's
// triples via proposalService.Edit.
func newProposalEditHandler(ps proposalService) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if !proposalIDPattern.MatchString(id) {
			mapEngineError(w, unknownProposalError(id))
			return
		}

		var req proposalEditRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeBadRequest(w, "malformed request body: "+err.Error())
			return
		}
		if strings.TrimSpace(req.Triples) == "" {
			// A body with no (or empty/whitespace-only) "triples" field is
			// well-formed JSON but not a valid triples body: calling Edit
			// with it would DROP the proposal graph and replace it with
			// nothing, silently destroying the staged proposal. Reject it
			// the same way a malformed body is rejected -- before Edit is
			// ever called -- so the proposal graph is left unchanged.
			writeBadRequest(w, "missing or empty \"triples\" field")
			return
		}

		if err := ps.Edit(r.Context(), id, req.Triples); err != nil {
			mapEngineError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, statusResponse{Status: "ok"})
	}
}

// proposalApproveRequest is the POST /api/proposals/{id}/approve
// request body.
type proposalApproveRequest struct {
	Reviewer  string `json:"reviewer"`
	Timestamp string `json:"timestamp"`
}

// newProposalApproveHandler builds the POST /api/proposals/{id}/approve
// handler: it promotes id via proposalService.Approve, carrying the
// request-supplied reviewer/timestamp into the decision-provenance
// record.
func newProposalApproveHandler(ps proposalService) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if !proposalIDPattern.MatchString(id) {
			mapEngineError(w, unknownProposalError(id))
			return
		}

		var req proposalApproveRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeBadRequest(w, "malformed request body: "+err.Error())
			return
		}

		approveReq := proposal.ApproveRequest{Reviewer: req.Reviewer, Timestamp: req.Timestamp}
		if err := ps.Approve(r.Context(), id, approveReq); err != nil {
			mapEngineError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, statusResponse{Status: "approved"})
	}
}

// newProposalRejectHandler builds the POST /api/proposals/{id}/reject
// handler. An empty or absent request body is allowed (spec "Reject"):
// io.EOF (no body at all, or a body that is only whitespace) is not
// treated as malformed, but any body present that fails to parse as JSON
// is.
func newProposalRejectHandler(ps proposalService) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if !proposalIDPattern.MatchString(id) {
			mapEngineError(w, unknownProposalError(id))
			return
		}

		var discard map[string]any
		if err := json.NewDecoder(r.Body).Decode(&discard); err != nil && !errors.Is(err, io.EOF) {
			writeBadRequest(w, "malformed request body: "+err.Error())
			return
		}

		if err := ps.Reject(r.Context(), id); err != nil {
			mapEngineError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, statusResponse{Status: "rejected"})
	}
}
