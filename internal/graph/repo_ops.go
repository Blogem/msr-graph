package graph

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
)

// ExportRepo GETs the whole repository as one TriG document (Accept:
// application/x-trig) via the RDF4J /repositories/{repo}/statements
// endpoint -- every named graph (including staging and proposal graphs)
// serialized together, quads and all, in a single response body. It is
// the read half of the checkpoint/restore round-trip (design D4); the
// caller is responsible for persisting the returned bytes.
func (c *Client) ExportRepo(ctx context.Context) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.updateEndpoint(), nil)
	if err != nil {
		return nil, fmt.Errorf("graph: build export request: %w", err)
	}
	req.Header.Set("Accept", "application/x-trig")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("graph: export request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("graph: read export response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("graph: export failed: %s: %s", resp.Status, bytes.TrimSpace(body))
	}
	return body, nil
}

// ClearRepo empties the entire repository: a DELETE against the
// statements endpoint with no subject/predicate/object/context query
// parameter deletes every triple in every named graph (RDF4J's
// context-less DELETE semantics), not just one graph. It is the
// destructive half of restore (design D4), always followed by
// ImportRepo to reload a checkpoint's TriG snapshot.
func (c *Client) ClearRepo(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodDelete, c.updateEndpoint(), nil)
	if err != nil {
		return fmt.Errorf("graph: build clear request: %w", err)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("graph: clear request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("graph: read clear response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("graph: clear failed: %s: %s", resp.Status, bytes.TrimSpace(body))
	}
	return nil
}

// ImportRepo POSTs trig (a full TriG document, as produced by ExportRepo)
// to the statements endpoint with Content-Type: application/x-trig,
// loading it into the repository's named graphs as given -- the load
// half of restore. Like Update, a non-2xx response is checked for a
// SHACL validation report first (detectValidationError) so a rejected
// restore surfaces the same typed *ValidationError callers already
// handle for ordinary writes.
func (c *Client) ImportRepo(ctx context.Context, trig []byte) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.updateEndpoint(), bytes.NewReader(trig))
	if err != nil {
		return fmt.Errorf("graph: build import request: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-trig")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("graph: import request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("graph: read import response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		if ve := detectValidationError(body); ve != nil {
			return ve
		}
		return fmt.Errorf("graph: import failed: %s: %s", resp.Status, bytes.TrimSpace(body))
	}
	return nil
}

// ProposalGraph builds the dedicated named-graph IRI a proposal's
// candidate triples live in: urn:msr:proposal/{id}, where id is the
// deterministic {kind}-{term-slug} segment chunk 8 already derives (e.g.
// "property-solubility"). Unlike Ontology/Data/Vocab/Staging, there is
// deliberately no Proposal graph constant and proposal graphs are never
// added to the PutGraph knownGraphs allowlist: they are dynamic
// (one per proposal, id-keyed) and PutGraph's destructive graph-replace
// semantics are the wrong tool for a graph a reviewer might be
// concurrently editing. Callers reach a proposal graph through Update
// (as an explicit GRAPH target) or SelectRaw.
//
// A single-named-graph read needs no dedicated helper: it is already
// cleanly expressible as SelectRaw with an explicit dataset scope,
// e.g. "SELECT ?s ?p ?o WHERE { GRAPH <"+string(ProposalGraph(id))+"> { ?s ?p ?o } }".
// Adding a ReadProposalGraph-style wrapper here would just rebuild that
// one-line query string behind a second API for no behavioral gain, so
// it is intentionally omitted.
func ProposalGraph(id string) GraphIRI {
	return GraphIRI("urn:msr:proposal/" + id)
}
