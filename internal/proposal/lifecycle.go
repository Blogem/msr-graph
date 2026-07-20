package proposal

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/blogem/msr-graph/internal/graph"
)

// Sentinel errors the HTTP layer (chunk 9's handlers) maps to status
// codes. Both are returned unwrapped-comparable via errors.Is/errors.As
// (wrapped with %w, never swallowed), so a caller can distinguish "no
// such proposal" from "wrong status for this transition" without
// string-matching an error message.
var (
	// ErrNotFound is returned when id has no matching msr:ChangeProposal
	// resource (i.e. no msr:reviewStatus triple for it) in
	// urn:msr:staging.
	ErrNotFound = errors.New("proposal: not found")
	// ErrInvalidTransition is returned when the requested transition is
	// not valid for the proposal's current review status -- e.g.
	// rejecting a proposal that is already approved, or approving one
	// that was rejected. The proposal is left untouched; no partial
	// mutation occurs.
	ErrInvalidTransition = errors.New("proposal: invalid status transition")
)

// ApproveRequest carries the request-supplied decision metadata an
// approval's provenance record needs (design D3).
type ApproveRequest struct {
	// Reviewer identifies the reviewer agent for prov:wasAssociatedWith.
	// It accepts either an absolute IRI (used verbatim) or a bare
	// identifier such as a username or email address, which is minted
	// into a deterministic urn:msr:agent/{slug} IRI -- see
	// normalizeReviewerIRI.
	Reviewer string
	// Timestamp is the request-supplied prov:startedAtTime, in the
	// xsd:dateTime lexical form.
	Timestamp string
}

// Approve promotes the pending proposal id (the deterministic
// "{kind}-{term-slug}" segment) into the core graphs: it routes the
// proposal graph's triples by type, minor-bumps the ontology version,
// records a decision-provenance activity, and flips msr:reviewStatus to
// "approved" -- all as one atomic SPARQL UPDATE (design D1/D2/D3), so a
// SHACL rejection rolls back every part of the promotion and the
// proposal stays pending.
//
// The status is read first (guard-first, D2/D5): an already-approved
// proposal is a no-op (idempotent re-approval, no second version bump,
// no duplicate work); any status other than "pending" or "approved"
// (e.g. "rejected") or an unknown id is refused via ErrNotFound /
// ErrInvalidTransition without mutating anything.
func (e *Engine) Approve(ctx context.Context, id string, req ApproveRequest) error {
	status, err := e.currentStatus(ctx, id)
	if err != nil {
		return err
	}
	switch status {
	case "approved":
		// Idempotent no-op: the decision was already made, so re-running
		// it must not bump the version or duplicate the promotion.
		return nil
	case "pending":
		// Falls through to the full promotion below.
	default:
		return fmt.Errorf("%w: proposal %q has status %q, not pending", ErrInvalidTransition, id, status)
	}

	reviewerIRI, err := normalizeReviewerIRI(req.Reviewer)
	if err != nil {
		return fmt.Errorf("proposal: approve %q: %w", id, err)
	}

	oldVersion, err := e.currentOntologyVersion(ctx)
	if err != nil {
		return fmt.Errorf("proposal: approve %q: %w", id, err)
	}
	newVersion, err := BumpMinor(oldVersion)
	if err != nil {
		return fmt.Errorf("proposal: approve %q: %w", id, err)
	}

	proposalGraph := string(graph.ProposalGraph(id))
	ops := routingUpdates(proposalGraph)
	ops = append(ops,
		versionBumpUpdate(newVersion),
		statusFlipUpdate(id, "approved"),
		approvalProvenanceUpdate(id, reviewerIRI, req.Timestamp),
	)
	combined := strings.Join(ops, " ;\n")

	if err := e.gc.Update(ctx, combined); err != nil {
		var ve *graph.ValidationError
		if errors.As(err, &ve) {
			// Surfaced as-is: GraphDB rolled the whole single-transaction
			// UPDATE back, so the proposal is still pending. Returning the
			// typed error unwrapped lets the HTTP layer errors.As it.
			return err
		}
		return fmt.Errorf("proposal: approve %q: %w", id, err)
	}
	return nil
}

// Reject transitions the pending proposal id to "rejected": it flips
// msr:reviewStatus only -- no core-graph copy, no version bump, and the
// proposal graph is left in place. Rejecting a proposal that is not
// currently pending (already rejected, or approved) is refused via
// ErrInvalidTransition with no mutation.
func (e *Engine) Reject(ctx context.Context, id string) error {
	status, err := e.currentStatus(ctx, id)
	if err != nil {
		return err
	}
	if status != "pending" {
		return fmt.Errorf("%w: proposal %q has status %q, not pending", ErrInvalidTransition, id, status)
	}

	if err := e.gc.Update(ctx, statusFlipUpdate(id, "rejected")); err != nil {
		var ve *graph.ValidationError
		if errors.As(err, &ve) {
			return err
		}
		return fmt.Errorf("proposal: reject %q: %w", id, err)
	}
	return nil
}

// Edit replaces the triples in the proposal's urn:msr:proposal/{id}
// graph with triples (Turtle/N-Triples body content, using this
// package's CURIEs -- see turtlePrefixes -- for anything it references
// by prefix). The msr:ChangeProposal resource's status is untouched (it
// stays "pending"); a subsequent detail read or Approve operates on the
// edited triples.
//
// triples is sent to GraphDB as the raw HTTP request body of a Graph
// Store Protocol PUT (graph.Client.PutProposalGraph), parsed server-side
// as Turtle -- never spliced into a SPARQL UPDATE string in Go. Building
// "INSERT DATA { GRAPH <..> { " + triples + " } }" would let a triples
// value containing e.g. "} } ; CLEAR ALL ; ..." break out of the INSERT
// block and run arbitrary SPARQL (a confirmed SPARQL-injection finding);
// PUT-replace has no such surface because GraphDB's Turtle parser, not
// its SPARQL parser, ever sees this content.
func (e *Engine) Edit(ctx context.Context, id string, triples string) error {
	document := turtlePrefixes + triples

	if err := e.gc.PutProposalGraph(ctx, id, []byte(document)); err != nil {
		var ve *graph.ValidationError
		if errors.As(err, &ve) {
			return err
		}
		return fmt.Errorf("proposal: edit %q: %w", id, err)
	}
	return nil
}

// currentStatus reads id's msr:reviewStatus from urn:msr:staging via
// SelectRaw with an explicit GRAPH scope (staging is excluded from
// Select's core-dataset restriction). It returns ErrNotFound if id has
// no msr:ChangeProposal resource carrying that predicate.
func (e *Engine) currentStatus(ctx context.Context, id string) (string, error) {
	query := sparqlPrefixes + fmt.Sprintf(
		"SELECT ?status WHERE { GRAPH <%s> { %s msr:reviewStatus ?status } }",
		graph.Staging, proposalResourceIRI(id),
	)
	results, err := e.gc.SelectRaw(ctx, query)
	if err != nil {
		return "", fmt.Errorf("proposal: read status for %q: %w", id, err)
	}
	if len(results.Results.Bindings) == 0 {
		return "", fmt.Errorf("%w: %q", ErrNotFound, id)
	}
	return results.Results.Bindings[0]["status"].Value, nil
}

// currentOntologyVersion reads the owl:versionInfo literal of the
// owl:Ontology header via the core-dataset Select (urn:msr:ontology is
// one of graph.CoreGraphs, so no explicit GRAPH scope is needed).
func (e *Engine) currentOntologyVersion(ctx context.Context) (string, error) {
	query := sparqlPrefixes + "SELECT ?v WHERE { ?ont a owl:Ontology ; owl:versionInfo ?v }"
	results, err := e.gc.Select(ctx, query)
	if err != nil {
		return "", fmt.Errorf("read ontology version: %w", err)
	}
	if len(results.Results.Bindings) == 0 {
		return "", fmt.Errorf("no owl:Ontology header with owl:versionInfo found in %s", graph.Ontology)
	}
	return results.Results.Bindings[0]["v"].Value, nil
}

// versionBumpUpdate returns the scoped DELETE/INSERT that replaces the
// single owl:versionInfo literal on the owl:Ontology header in
// urn:msr:ontology with newVersion (design D2). The WHERE clause
// re-locates the header itself (rather than requiring a caller-known
// IRI), so it fires only when the header still carries a versionInfo
// value at execution time.
func versionBumpUpdate(newVersion string) string {
	return sparqlPrefixes + fmt.Sprintf(`DELETE { GRAPH <%s> { ?ont owl:versionInfo ?old } }
INSERT { GRAPH <%s> { ?ont owl:versionInfo "%s" } }
WHERE { GRAPH <%s> { ?ont a owl:Ontology ; owl:versionInfo ?old } }`,
		graph.Ontology, graph.Ontology, escapeLiteral(newVersion), graph.Ontology)
}

// statusFlipUpdate returns the scoped DELETE/INSERT that sets id's
// msr:reviewStatus in urn:msr:staging to newStatus, replacing whatever
// value it currently holds.
func statusFlipUpdate(id, newStatus string) string {
	subject := proposalResourceIRI(id)
	return sparqlPrefixes + fmt.Sprintf(`DELETE { GRAPH <%s> { %s msr:reviewStatus ?old } }
INSERT { GRAPH <%s> { %s msr:reviewStatus "%s" } }
WHERE { GRAPH <%s> { %s msr:reviewStatus ?old } }`,
		graph.Staging, subject, graph.Staging, subject, escapeLiteral(newStatus), graph.Staging, subject)
}

// approvalProvenanceUpdate returns the INSERT DATA that appends the
// decision-provenance activity for id's approval into urn:msr:staging
// (design D3, never urn:msr:provenance): a prov:Activity at
// urn:msr:run:approve/{id}, prov:wasAssociatedWith reviewerIRI (already
// normalized to an absolute IRI by normalizeReviewerIRI -- GraphDB
// rejects the whole UPDATE if this is a relative IRI), prov:startedAtTime
// the request-supplied timestamp, and a prov:wasGeneratedBy edge from
// the approved msr:ChangeProposal to that activity -- reusing the same
// PROV-O predicate chunk 8 already uses to attribute a proposal to its
// mine run, just recorded in staging against a different (governance,
// not pipeline-generation) activity.
func approvalProvenanceUpdate(id, reviewerIRI, timestamp string) string {
	activity := "urn:msr:run:approve/" + id
	subject := proposalResourceIRI(id)
	return sparqlPrefixes + fmt.Sprintf(`INSERT DATA { GRAPH <%s> {
    <%s> a prov:Activity ;
        prov:wasAssociatedWith <%s> ;
        prov:startedAtTime "%s"^^xsd:dateTime .
    %s prov:wasGeneratedBy <%s> .
} }`, graph.Staging, activity, reviewerIRI, escapeLiteral(timestamp), subject, activity)
}
