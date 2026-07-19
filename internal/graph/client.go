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

// datasetKeywordPattern matches a standalone FROM token (case
// insensitively) in dataset-clause position: a real FROM / FROM NAMED
// clause is always whitespace- or start-delimited, so requiring a leading
// boundary means the pattern does not fire on a "from" that is a variable
// (?from), a prefixed name (ex:from), or part of a longer word (fromage).
// FROM NAMED is caught by the same pattern since it begins with FROM. The
// pattern is applied to text with string literals, IRIs, and comments
// already neutralised (see stripNonKeywordText), so a "from" inside those
// is never seen here.
var datasetKeywordPattern = regexp.MustCompile(`(?i)(?:^|\s)from\b`)

// rejectDatasetClause rejects queries that carry their own FROM/FROM
// NAMED dataset clause, so a query cannot smuggle in a wider dataset than
// the protocol parameters Select sends. The scan ignores a "from" that
// appears inside a string literal, an IRI, or a comment -- there it is
// data, not a dataset clause -- so legitimate core reads such as
// FILTER(CONTAINS(?o, "from")) or a ?from variable are not rejected. The
// protocol dataset parameters remain the actual isolation boundary; this
// guard is defense-in-depth plus a clear error pointing at SelectRaw.
func rejectDatasetClause(query string) error {
	if datasetKeywordPattern.MatchString(stripNonKeywordText(query)) {
		return fmt.Errorf("graph: Select does not accept queries with a FROM/FROM NAMED clause (query would override the core-dataset restriction); use SelectRaw for unrestricted reads")
	}
	return nil
}

// stripNonKeywordText replaces SPARQL string literals, IRIs, and comments
// with single spaces so a keyword scan over the result cannot be fooled by
// a keyword-looking substring inside quoted text, an IRI path, or a
// comment. It is deliberately lenient: it neutralises those spans, it does
// not fully validate SPARQL.
func stripNonKeywordText(q string) string {
	var b strings.Builder
	b.Grow(len(q))
	for i := 0; i < len(q); {
		switch c := q[i]; {
		case c == '#':
			// Line comment: skip to (but not past) the end of line, so
			// the newline stays as a token delimiter.
			j := i + 1
			for j < len(q) && q[j] != '\n' {
				j++
			}
			b.WriteByte(' ')
			i = j
		case c == '"' || c == '\'':
			b.WriteByte(' ')
			i = skipString(q, i)
		case c == '<':
			if end, ok := iriEnd(q, i); ok {
				b.WriteByte(' ')
				i = end
			} else {
				// A lone '<' (e.g. a less-than operator), not an IRIREF.
				b.WriteByte(c)
				i++
			}
		default:
			b.WriteByte(c)
			i++
		}
	}
	return b.String()
}

// skipString consumes a SPARQL string literal starting at q[i] (a quote
// character) and returns the index just past its closing delimiter. It
// handles both short ("..."/'...') and long ("""..."""/”'...”') forms
// and backslash escapes. An unterminated literal is consumed to end of
// line (short) or end of input (long).
func skipString(q string, i int) int {
	quote := q[i]
	if i+2 < len(q) && q[i+1] == quote && q[i+2] == quote {
		for j := i + 3; j < len(q); {
			if q[j] == '\\' {
				j += 2
				continue
			}
			if q[j] == quote && j+2 < len(q) && q[j+1] == quote && q[j+2] == quote {
				return j + 3
			}
			j++
		}
		return len(q)
	}
	for j := i + 1; j < len(q); {
		switch q[j] {
		case '\\':
			j += 2
		case quote:
			return j + 1
		case '\n':
			return j
		default:
			j++
		}
	}
	return len(q)
}

// iriEnd reports whether q[i] (a '<') begins an IRIREF and, if so, the
// index just past its closing '>'. An IRIREF contains no whitespace and
// none of <>"{}|^` (or a backslash), and ends with '>'; if those do not
// hold, the '<' is something else (e.g. a less-than operator) and ok is
// false.
func iriEnd(q string, i int) (int, bool) {
	for j := i + 1; j < len(q); j++ {
		switch c := q[j]; {
		case c == '>':
			return j + 1, true
		case c <= ' ', c == '<', c == '"', c == '{', c == '}', c == '|', c == '^', c == '`', c == '\\':
			return 0, false
		}
	}
	return 0, false
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
