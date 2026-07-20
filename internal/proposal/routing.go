package proposal

import "github.com/blogem/msr-graph/internal/graph"

// Filter expressions classifying one proposal-graph triple (?s ?p ?o) by
// what it IS, not by the proposal's display msr:kind (design D1,
// approval-typed-routing spec's "Triples are routed to core graphs by
// type" requirement). Each is a self-contained, parenthesized SPARQL
// boolean so the three compose safely with && / ! to partition the
// proposal graph with no overlap and no gap:
//
//   - vocabFilter matches every triple about a subject the bundle
//     declares a skos:Concept (its "a skos:Concept" triple, prefLabel,
//     altLabel, broader, definition, ...), plus -- as a safety net for a
//     SKOS-predicate triple whose subject-typing triple is not itself
//     part of this bundle -- any triple whose predicate is in the SKOS
//     namespace.
//   - ontologyFilter matches every triple about a subject the bundle
//     declares an owl:Class/owl:ObjectProperty/owl:DatatypeProperty or an
//     msr:PhysicalProperty individual (so a property's rdfs:label,
//     msr:quantityKind, and msr:canonicalUnit travel with it), plus the
//     rdfs:subClassOf/domain/range predicates regardless of subject
//     typing.
//   - dataFilter (see routingUpdates) is the negation of both, so
//     everything left over -- individuals and the edges between them --
//     lands in urn:msr:data.
const (
	vocabFilter = `(EXISTS { ?s a skos:Concept } || STRSTARTS(STR(?p), "http://www.w3.org/2004/02/skos/core#"))`

	ontologyFilter = `(EXISTS { ?s a owl:Class } || EXISTS { ?s a owl:ObjectProperty } || ` +
		`EXISTS { ?s a owl:DatatypeProperty } || ?p = rdfs:subClassOf || ?p = rdfs:domain || ` +
		`?p = rdfs:range || EXISTS { ?s a msr:PhysicalProperty })`
)

// routingInsert returns one standalone "INSERT { GRAPH <dest> {...} }
// WHERE { GRAPH <proposalGraph> {...FILTER...} }" copy operation, a full
// SPARQL Update string (own Prologue included) so it can be used alone
// or joined with ";" into a larger update.
func routingInsert(proposalGraph, dest, filterExpr string) string {
	return sparqlPrefixes + `
INSERT { GRAPH <` + dest + `> { ?s ?p ?o } }
WHERE {
  GRAPH <` + proposalGraph + `> {
    ?s ?p ?o .
    FILTER(` + filterExpr + `)
  }
}`
}

// routingUpdates returns the three filtered copy operations that route
// proposalGraph's triples into urn:msr:vocab, urn:msr:ontology, and
// urn:msr:data by type. dataFilter is the negation of vocabFilter and
// ontologyFilter, so the three together partition every triple in the
// proposal graph into exactly one destination.
func routingUpdates(proposalGraph string) []string {
	dataFilter := `!(` + vocabFilter + ` || ` + ontologyFilter + `)`
	return []string{
		routingInsert(proposalGraph, string(graph.Vocab), vocabFilter),
		routingInsert(proposalGraph, string(graph.Ontology), ontologyFilter),
		routingInsert(proposalGraph, string(graph.Data), dataFilter),
	}
}
