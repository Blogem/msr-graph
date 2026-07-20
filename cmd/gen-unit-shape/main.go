// Command gen-unit-shape generates a SHACL fragment constraining
// msr:hasUnit to the QUDT unit allowlist declared in
// ontology/qudt-units.json, so the shape and the loader's allowlist share
// one source of truth (openspec/changes/shacl-validation/design.md D3,
// tasks.md 3.1).
//
// Usage:
//
//	go run ./cmd/gen-unit-shape [-units ontology/qudt-units.json] [-o deploy/graphdb/msr-shapes-units.ttl]
//
// The generated file is a standalone Turtle document intended to be loaded
// into the reserved SHACL shapes graph alongside the hand-authored
// deploy/graphdb/msr-shapes.ttl.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
)

const (
	defaultUnitsPath  = "ontology/qudt-units.json"
	defaultOutputPath = "deploy/graphdb/msr-shapes-units.ttl"

	msrNamespace = "https://w3id.org/msr-kg/ontology#"
)

// unitsFile is the minimal shape of ontology/qudt-units.json needed to emit
// the allowlist. Only AllowedUnits is used; other fields (prefixes,
// properties, allowedQuantityKinds) are ignored here.
type unitsFile struct {
	AllowedUnits []string `json:"allowedUnits"`
}

func main() {
	unitsPath := flag.String("units", defaultUnitsPath, "path to ontology/qudt-units.json")
	outPath := flag.String("o", defaultOutputPath, "output path for the generated SHACL fragment")
	flag.Parse()

	if err := run(*unitsPath, *outPath); err != nil {
		fmt.Fprintln(os.Stderr, "gen-unit-shape:", err)
		os.Exit(1)
	}
}

func run(unitsPath, outPath string) error {
	units, err := loadAllowedUnits(unitsPath)
	if err != nil {
		return fmt.Errorf("load allowed units: %w", err)
	}
	if len(units) == 0 {
		return fmt.Errorf("no allowedUnits found in %s", unitsPath)
	}

	doc := renderShape(units, unitsPath)

	if err := os.WriteFile(outPath, []byte(doc), 0o644); err != nil {
		return fmt.Errorf("write %s: %w", outPath, err)
	}
	return nil
}

// loadAllowedUnits reads unitsPath and returns its allowedUnits array in
// file order (order is preserved so the emitted sh:in list is
// deterministic and matches the source exactly).
func loadAllowedUnits(unitsPath string) ([]string, error) {
	data, err := os.ReadFile(unitsPath)
	if err != nil {
		return nil, err
	}

	var f unitsFile
	if err := json.Unmarshal(data, &f); err != nil {
		return nil, fmt.Errorf("parse %s: %w", unitsPath, err)
	}
	return f.AllowedUnits, nil
}

// renderShape renders the standalone Turtle document containing the
// generated NodeShape.
func renderShape(units []string, sourcePath string) string {
	var b strings.Builder

	b.WriteString("# GENERATED FILE — do not hand-edit.\n")
	b.WriteString("#\n")
	fmt.Fprintf(&b, "# Generated from %s by cmd/gen-unit-shape.\n", sourcePath)
	b.WriteString("# Re-run `go run ./cmd/gen-unit-shape` to regenerate after the allowlist changes.\n")
	b.WriteString("#\n")
	b.WriteString("# Constrains msr:hasUnit on msr:PropertyMeasurement to the QUDT unit\n")
	b.WriteString("# allowlist, so the shape and the loader's allowlist share one source of\n")
	b.WriteString("# truth (openspec/changes/shacl-validation/design.md D3). This fragment is\n")
	b.WriteString("# loaded into the reserved SHACL shapes graph alongside the hand-authored\n")
	b.WriteString("# deploy/graphdb/msr-shapes.ttl, which owns the minCount/cardinality\n")
	b.WriteString("# constraint on msr:hasUnit — this fragment only constrains the value set.\n")
	b.WriteString("\n")
	fmt.Fprintf(&b, "@prefix msr: <%s> .\n", msrNamespace)
	b.WriteString("@prefix sh:  <http://www.w3.org/ns/shacl#> .\n")
	b.WriteString("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n")
	b.WriteString("\n")
	b.WriteString("msr:PropertyMeasurementUnitAllowlistShape\n")
	b.WriteString("    a sh:NodeShape ;\n")
	b.WriteString("    sh:targetClass msr:PropertyMeasurement ;\n")
	b.WriteString("    sh:property [\n")
	b.WriteString("        sh:path msr:hasUnit ;\n")
	b.WriteString("        sh:in (\n")
	for _, u := range units {
		fmt.Fprintf(&b, "            <%s>\n", u)
	}
	b.WriteString("        ) ;\n")
	b.WriteString("        sh:message \"msr:hasUnit must be one of the QUDT units in ontology/qudt-units.json's allowedUnits.\" ;\n")
	b.WriteString("    ] .\n")

	return b.String()
}
