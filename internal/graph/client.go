package graph

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
)

// datasetClausePattern matches a standalone "FROM" token, case
// insensitively. It is a word-boundary scan rather than a naive
// substring check so it does not fire on "FROM" appearing inside a
// larger identifier (e.g. "fromage"); "FROM NAMED" is caught by the
// same pattern since it starts with the "FROM" token.
var datasetClausePattern = regexp.MustCompile(`(?i)\bfrom\b`)

// rejectDatasetClause rejects queries that carry their own FROM/FROM
// NAMED dataset clause, so a query cannot smuggle in a wider dataset
// than the protocol parameters Select sends.
func rejectDatasetClause(query string) error {
	if datasetClausePattern.MatchString(query) {
		return fmt.Errorf("graph: Select does not accept queries with a FROM/FROM NAMED clause (query would override the core-dataset restriction); use SelectRaw for unrestricted reads")
	}
	return nil
}

// queryEndpoint is the SPARQL 1.1 Protocol query endpoint.
func (c *Client) queryEndpoint() string {
	return c.baseURL + "/repositories/" + c.repo
}

// updateEndpoint is the SPARQL 1.1 Protocol update endpoint.
func (c *Client) updateEndpoint() string {
	return c.baseURL + "/repositories/" + c.repo + "/statements"
}

// graphStoreEndpoint is the SPARQL 1.1 Graph Store Protocol endpoint
// for the given graph IRI.
func (c *Client) graphStoreEndpoint(g GraphIRI) string {
	params := url.Values{}
	params.Set("graph", string(g))
	return c.baseURL + "/repositories/" + c.repo + "/rdf-graphs/service?" + params.Encode()
}

// Select runs a core-dataset read: query is evaluated against exactly
// the three core graphs (CoreGraphs), sent as both default-graph-uri
// and named-graph-uri protocol parameters. Queries carrying their own
// FROM/FROM NAMED clause are rejected before any HTTP call is made;
// use SelectRaw for deliberately unrestricted reads.
func (c *Client) Select(ctx context.Context, query string) (*Results, error) {
	if err := rejectDatasetClause(query); err != nil {
		return nil, err
	}

	form := url.Values{}
	form.Set("query", query)
	for _, g := range CoreGraphs {
		form.Add("default-graph-uri", string(g))
	}
	for _, g := range CoreGraphs {
		form.Add("named-graph-uri", string(g))
	}
	return c.doSelect(ctx, form)
}

// SelectRaw runs query with no dataset restriction (GraphDB's default:
// union of all graphs). It is the escape hatch for staging-inclusive
// reads and for proving the core/raw difference.
func (c *Client) SelectRaw(ctx context.Context, query string) (*Results, error) {
	form := url.Values{}
	form.Set("query", query)
	return c.doSelect(ctx, form)
}

func (c *Client) doSelect(ctx context.Context, form url.Values) (*Results, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.queryEndpoint(), strings.NewReader(form.Encode()))
	if err != nil {
		return nil, fmt.Errorf("graph: build select request: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "application/sparql-results+json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("graph: select request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("graph: read select response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("graph: select failed: %s: %s", resp.Status, bytes.TrimSpace(body))
	}

	var results Results
	if err := json.Unmarshal(body, &results); err != nil {
		return nil, fmt.Errorf("graph: decode select response: %w", err)
	}
	return &results, nil
}

// Update runs a SPARQL 1.1 UPDATE. Writers name explicit GRAPH targets
// in the update string; the client does not add any dataset
// restriction to updates.
func (c *Client) Update(ctx context.Context, update string) error {
	form := url.Values{}
	form.Set("update", update)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.updateEndpoint(), strings.NewReader(form.Encode()))
	if err != nil {
		return fmt.Errorf("graph: build update request: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("graph: update request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("graph: read update response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("graph: update failed: %s: %s", resp.Status, bytes.TrimSpace(body))
	}
	return nil
}

// PutGraph replaces the contents of graphIRI with turtle via the SPARQL
// 1.1 Graph Store Protocol PUT (graph-replace semantics). It refuses
// graph IRIs outside the exported constant set (Ontology, Data, Vocab,
// Staging) without sending any request to GraphDB, since PUT is
// destructive and a wrong IRI would silently wipe good data.
func (c *Client) PutGraph(ctx context.Context, graphIRI GraphIRI, turtle []byte) error {
	if !knownGraphs[graphIRI] {
		return fmt.Errorf("graph: PutGraph refuses unknown graph IRI %q; must be one of the graph constants exported by this package", graphIRI)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPut, c.graphStoreEndpoint(graphIRI), bytes.NewReader(turtle))
	if err != nil {
		return fmt.Errorf("graph: build PutGraph request: %w", err)
	}
	req.Header.Set("Content-Type", "text/turtle")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("graph: PutGraph request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("graph: read PutGraph response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("graph: PutGraph failed: %s: %s", resp.Status, bytes.TrimSpace(body))
	}
	return nil
}
