// Package proposal implements the proposal approval + lifecycle engine
// (openspec/changes/apply-ontology-changes, chunk 9): on approve it
// routes a staged msr:ChangeProposal's triples into the core graphs by
// triple type, bumps the ontology version, records decision provenance,
// and flips the review status -- all as one atomic, idempotent SPARQL
// UPDATE -- plus the reject and edit transitions with their guards. See
// design.md decisions D1 (typed routing), D2 (version bump), D3
// (decision provenance), D5 (idempotency) and specs
// approval-typed-routing / proposal-lifecycle for the normative
// requirements this package implements.
package proposal

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"github.com/blogem/msr-graph/internal/graph"
)

// GraphClient is the narrow, fakeable subset of *graph.Client the engine
// depends on: core reads, staging-inclusive raw reads, and additive
// updates with an explicit GRAPH target. Declaring it here rather than
// depending on *graph.Client directly keeps the engine unit-testable
// against a fake, mirroring internal/agent's GraphSelector seam.
type GraphClient interface {
	Select(ctx context.Context, query string) (*graph.Results, error)
	SelectRaw(ctx context.Context, query string) (*graph.Results, error)
	Update(ctx context.Context, update string) error
	// PutProposalGraph replaces proposal id's urn:msr:proposal/{id}
	// graph with turtle via the Graph Store Protocol -- the transport
	// Edit uses instead of splicing caller-supplied content into a
	// SPARQL UPDATE string (see graph.Client.PutProposalGraph's doc
	// comment for why that splice was a SPARQL-injection vector).
	PutProposalGraph(ctx context.Context, id string, turtle []byte) error
}

// Engine promotes, rejects, and edits msr:ChangeProposal resources
// staged in urn:msr:staging.
type Engine struct {
	gc GraphClient
}

// NewEngine builds an Engine backed by gc.
func NewEngine(gc GraphClient) *Engine {
	return &Engine{gc: gc}
}

// sparqlPrefixes are the PREFIX declarations shared by every query/
// update this package builds. They match the namespaces the extraction
// service (chunk 8) writes proposals under
// (extraction/src/msr_extraction/proposals.py's _PREFIXES), so a
// proposal's own CURIEs resolve the same way here. SPARQL 1.1 Update
// allows a fresh Prologue at the start of each ';'-separated operation,
// so every helper below prepends this block and the resulting update
// strings can be joined with ";" directly.
const sparqlPrefixes = `PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX voc: <https://w3id.org/msr-kg/vocab#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
`

// turtlePrefixes mirrors sparqlPrefixes' namespaces (plus the QUDT qk:/
// unit: prefixes ontology/msr.ttl itself declares, for a canonicalUnit/
// quantityKind CURIE) in Turtle @prefix syntax. Edit prepends this to
// the caller-supplied replacement triples before handing the whole
// document to graph.Client.PutProposalGraph, so a reviewer's edit body
// can use the same short CURIEs proposals are already written with.
const turtlePrefixes = `@prefix msr: <https://w3id.org/msr-kg/ontology#> .
@prefix msrd: <https://w3id.org/msr-kg/data#> .
@prefix voc: <https://w3id.org/msr-kg/vocab#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix qk: <http://qudt.org/vocab/quantitykind/> .
@prefix unit: <http://qudt.org/vocab/unit/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
`

// proposalResourceIRI returns the msrd:proposal-{id} CURIE for the
// msr:ChangeProposal resource identified by id -- chunk 8's
// deterministic "{kind}-{term-slug}" segment, the same one
// graph.ProposalGraph(id) derives the proposal graph IRI from.
func proposalResourceIRI(id string) string {
	return "msrd:proposal-" + id
}

// escapeLiteral escapes s for embedding inside a double-quoted Turtle/
// SPARQL string literal, mirroring the extraction service's
// _escape_literal (proposals.py) so a value containing quotes,
// backslashes, or newlines never breaks the generated update.
var literalEscaper = strings.NewReplacer(
	`\`, `\\`,
	`"`, `\"`,
	"\n", `\n`,
	"\t", `\t`,
	"\r", `\r`,
)

func escapeLiteral(s string) string {
	return literalEscaper.Replace(s)
}

// validateIRIRef rejects a string that could not be embedded inside a
// SPARQL/Turtle IRIREF (<...>): whitespace or any of <>"{}|^` would
// either break out of the IRIREF or be rejected by the parser. This
// mirrors the character class internal/graph's iriEnd checks for, so a
// caller-supplied reviewer identifier cannot smuggle SPARQL syntax into
// the single UPDATE request Approve builds.
func validateIRIRef(s string) error {
	if s == "" {
		return fmt.Errorf("proposal: reviewer IRI must not be empty")
	}
	for _, r := range s {
		switch {
		case r <= ' ', r == '<', r == '>', r == '"', r == '{', r == '}', r == '|', r == '^', r == '`', r == '\\':
			return fmt.Errorf("proposal: %q is not a valid IRI (contains %q)", s, r)
		}
	}
	return nil
}

// absoluteIRISchemePattern matches a leading RFC 3986 scheme
// ("scheme:", e.g. "http:", "https:", "urn:") at the start of a string --
// the signal that a caller-supplied reviewer value is already an
// absolute IRI rather than a bare identifier.
var absoluteIRISchemePattern = regexp.MustCompile(`^[a-zA-Z][a-zA-Z0-9+.-]*:`)

// agentSlugSafe reports whether r may appear unescaped in the minted
// urn:msr:agent/{slug} path segment: ASCII letters/digits plus a small,
// conservative punctuation set. Everything else -- including whitespace
// and the IRIREF-breaking characters validateIRIRef rejects -- is
// percent-escaped by mintAgentSlug instead of passed through.
func agentSlugSafe(r rune) bool {
	switch {
	case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
		return true
	case r == '-', r == '_', r == '.', r == '~':
		return true
	}
	return false
}

// mintAgentSlug percent-escapes reviewer into a deterministic, IRI-path-
// safe slug: every byte of a rune not in agentSlugSafe's charset is
// replaced by its %XX percent-encoding, so no whitespace or IRIREF-
// breaking character (space, <>"{}|^`\) ever reaches the minted IRI
// unescaped, and the same input always mints the same slug.
func mintAgentSlug(reviewer string) string {
	var b strings.Builder
	for _, r := range reviewer {
		if agentSlugSafe(r) {
			b.WriteRune(r)
			continue
		}
		for _, raw := range []byte(string(r)) {
			fmt.Fprintf(&b, "%%%02X", raw)
		}
	}
	return b.String()
}

// normalizeReviewerIRI turns ApproveRequest.Reviewer into an absolute
// IRI suitable for prov:wasAssociatedWith: a value that already carries
// a URI scheme (http://, https://, urn:, ...) is used verbatim; anything
// else -- the bare human/agent identifier the chunk-10 HTTP layer
// actually sends (e.g. "tester@example.com", "roundtrip-tester") -- is
// minted into a deterministic urn:msr:agent/{slug} IRI (mintAgentSlug).
// GraphDB rejects a SPARQL UPDATE embedding a relative IRI ("Not a valid
// (absolute) IRI"), so Approve must never pass a bare identifier through
// to the query unnormalized. The result is re-validated as a safe
// IRIREF before being returned.
func normalizeReviewerIRI(reviewer string) (string, error) {
	if reviewer == "" {
		return "", fmt.Errorf("proposal: reviewer must not be empty")
	}

	iri := reviewer
	if !absoluteIRISchemePattern.MatchString(reviewer) {
		iri = "urn:msr:agent/" + mintAgentSlug(reviewer)
	}

	if err := validateIRIRef(iri); err != nil {
		return "", fmt.Errorf("proposal: normalize reviewer %q: %w", reviewer, err)
	}
	return iri, nil
}
