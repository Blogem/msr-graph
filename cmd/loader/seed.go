package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/blogem/msr-graph/internal/graph"
)

// seedFile pairs a seed turtle file (relative to config.ontologyDir) with
// the named graph it is loaded into.
type seedFile struct {
	name     string
	graphIRI graph.GraphIRI
}

// seedFiles is the fixed seed-load manifest (task 5.1 / design D3).
var seedFiles = []seedFile{
	{name: "msr.ttl", graphIRI: graph.Ontology},
	{name: "vocab.ttl", graphIRI: graph.Vocab},
	{name: "example-flibe.ttl", graphIRI: graph.Data},
}

// runSeed implements `loader seed`: it PUTs each seed file to its named
// graph via graph.PutGraph (Graph Store PUT = graph-replace, so re-running
// yields identical triple counts per design D3), then ensures
// urn:msr:staging exists without touching any existing content in it.
func runSeed(env func(string) string, stdout io.Writer) error {
	cfg := loadConfig(env)
	client := graph.New(cfg.graphDBURL, cfg.graphDBRepo, nil)
	ctx := context.Background()

	for _, sf := range seedFiles {
		path := filepath.Join(cfg.ontologyDir, sf.name)
		turtle, err := os.ReadFile(path)
		if err != nil {
			return fmt.Errorf("seed: reading %s: %w", path, err)
		}

		fmt.Fprintf(stdout, "loader: seed: PUT %s -> %s\n", path, sf.graphIRI)
		if err := client.PutGraph(ctx, sf.graphIRI, turtle); err != nil {
			return fmt.Errorf("seed: loading %s into %s: %w", path, sf.graphIRI, err)
		}
	}

	// CREATE SILENT is a NO-OP when the graph already exists (preserving its
	// triples) and creates an empty graph when absent. This must NOT be a
	// PutGraph call: PutGraph's graph-replace semantics would wipe any
	// existing staging content.
	fmt.Fprintf(stdout, "loader: seed: ensuring staging graph %s exists\n", graph.Staging)
	update := fmt.Sprintf("CREATE SILENT GRAPH <%s>", graph.Staging)
	if err := client.Update(ctx, update); err != nil {
		return fmt.Errorf("seed: ensuring staging graph %s: %w", graph.Staging, err)
	}

	fmt.Fprintln(stdout, "loader: seed: load complete")
	return nil
}
