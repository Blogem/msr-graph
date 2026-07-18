// Package graph provides a GraphDB SPARQL client that enforces the
// core-dataset contract (urn:msr:ontology, urn:msr:data, urn:msr:vocab)
// on reads, with an explicit escape hatch for staging-inclusive queries
// and named-graph writes.
//
// This package is the only one that knows the SPARQL endpoint
// configuration; every other package talks to GraphDB exclusively
// through Client. Core reads (Select) evaluate against exactly the
// three core graphs by sending them as both default-graph-uri and
// named-graph-uri SPARQL 1.1 Protocol parameters — GraphDB has no
// store-side graph exclusion and its no-dataset default is
// union-of-all-graphs, so this client is the enforcement of the
// core-dataset contract, not a convenience wrapper around it.
package graph

import (
	"net/http"
	"time"
)

// defaultTimeout bounds requests made by the default HTTP client used
// when New is called with a nil httpClient.
const defaultTimeout = 30 * time.Second

// GraphIRI identifies one of the named graphs known to this deployment.
// Call sites use these typed constants instead of literal IRI strings.
type GraphIRI string

// Named-graph IRIs used by the msr-graph deployment.
const (
	// Ontology holds the MSR ontology (TBox).
	Ontology GraphIRI = "urn:msr:ontology"
	// Data holds core measurement/instance data (ABox).
	Data GraphIRI = "urn:msr:data"
	// Vocab holds the shared vocabulary/term graph.
	Vocab GraphIRI = "urn:msr:vocab"
	// Staging holds unreviewed proposals; deliberately excluded from
	// core reads (Select) and only reachable via SelectRaw.
	Staging GraphIRI = "urn:msr:staging"
)

// CoreGraphs are the three graphs a core read is restricted to, in a
// stable order.
var CoreGraphs = []GraphIRI{Ontology, Data, Vocab}

// knownGraphs is the full exported constant set (core graphs plus
// staging) that PutGraph is allowed to target. It exists so a typo'd
// or otherwise unknown graph IRI is refused before any HTTP request is
// made, protecting against Graph Store PUT's destructive graph-replace
// semantics.
var knownGraphs = map[GraphIRI]bool{
	Ontology: true,
	Data:     true,
	Vocab:    true,
	Staging:  true,
}

// Client talks to one GraphDB repository's SPARQL endpoints.
type Client struct {
	baseURL    string
	repo       string
	httpClient *http.Client
}

// New builds a Client for repo `repo` at GraphDB base URL `baseURL`
// (e.g. "http://localhost:7200", "msr"). httpClient may be nil, in
// which case a client with a sane default timeout is used; tests
// inject a client with a custom Transport for dependency injection.
func New(baseURL, repo string, httpClient *http.Client) *Client {
	if httpClient == nil {
		httpClient = &http.Client{Timeout: defaultTimeout}
	}
	return &Client{
		baseURL:    trimTrailingSlash(baseURL),
		repo:       repo,
		httpClient: httpClient,
	}
}

func trimTrailingSlash(s string) string {
	for len(s) > 0 && s[len(s)-1] == '/' {
		s = s[:len(s)-1]
	}
	return s
}

// Results is the SPARQL 1.1 JSON results shape.
type Results struct {
	Head struct {
		Vars []string `json:"vars"`
	} `json:"head"`
	Results struct {
		Bindings []map[string]Binding `json:"bindings"`
	} `json:"results"`
}

// Binding is a single RDF term bound to a variable in a SPARQL JSON
// result row.
type Binding struct {
	Type     string `json:"type"`
	Value    string `json:"value"`
	Datatype string `json:"datatype,omitempty"`
	XMLLang  string `json:"xml:lang,omitempty"`
}
