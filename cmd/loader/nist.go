package main

import (
	"context"
	"database/sql"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/nist"
	"github.com/blogem/msr-graph/internal/store"
)

// qudtAllowlistFile is the vendored QUDT unit/quantity-kind allowlist,
// resolved relative to config.ontologyDir (it lives alongside the seed
// turtle files, not under the NIST data directory).
const qudtAllowlistFile = "qudt-units.json"

// runNist implements `loader nist`: it runs the pure internal/nist
// transformation core over the vendored CSVs (task contract step 3),
// upserts the resulting rows into SQLite (numeric coefficients live only
// there), sends an additive SPARQL INSERT DATA of the catalog triples into
// urn:msr:data, and prints a run summary.
func runNist(env func(string) string, stdout io.Writer) error {
	cfg := loadConfig(env)
	ctx := context.Background()

	unitsPath := filepath.Join(cfg.ontologyDir, qudtAllowlistFile)
	units, err := nist.LoadUnitAllowlist(unitsPath)
	if err != nil {
		return fmt.Errorf("nist: loading unit allowlist %s: %w", unitsPath, err)
	}

	measurements, summary, err := nist.Process(cfg.nistDir, units)
	if err != nil {
		return fmt.Errorf("nist: processing %s: %w", cfg.nistDir, err)
	}

	dir := filepath.Dir(cfg.dbPath)
	if err := os.MkdirAll(dir, 0o775); err != nil {
		return fmt.Errorf("nist: creating database directory %s: %w", dir, err)
	}

	db, err := store.Open(cfg.dbPath)
	if err != nil {
		return fmt.Errorf("nist: opening %s: %w", cfg.dbPath, err)
	}
	defer db.Close()

	if err := store.Init(ctx, db); err != nil {
		return fmt.Errorf("nist: applying schema: %w", err)
	}

	rows := make([]store.MeasurementRow, 0, len(measurements))
	for _, m := range measurements {
		rows = append(rows, measurementToRow(m))
	}
	if err := store.Upsert(ctx, db, rows); err != nil {
		return fmt.Errorf("nist: upserting measurement rows: %w", err)
	}

	client := graph.New(cfg.graphDBURL, cfg.graphDBRepo, nil)
	sparql := buildInsertData(measurements)
	if err := client.Update(ctx, sparql); err != nil {
		return fmt.Errorf("nist: inserting catalog triples into %s: %w", graph.Data, err)
	}

	printNistSummary(stdout, summary)
	fmt.Fprintln(stdout, "loader: nist: load complete")
	return nil
}

// measurementToRow maps one nist.Measurement to a store.MeasurementRow.
// Numeric coefficients (c0..c4) and the validity range live only in
// SQLite -- they are never emitted as graph triples (buildInsertData
// deliberately omits them). A nil coefficient/temperature pointer becomes
// an invalid (NULL) sql.NullFloat64 rather than a zero value, so absent
// data is never mistaken for a real 0.
func measurementToRow(m nist.Measurement) store.MeasurementRow {
	return store.MeasurementRow{
		Locator:      m.Locator,
		Salt:         nullString(m.Salt.Canonical),
		Property:     nullString(m.Property),
		C0:           nullFloat(m.Coeffs[0]),
		C1:           nullFloat(m.Coeffs[1]),
		C2:           nullFloat(m.Coeffs[2]),
		C3:           nullFloat(m.Coeffs[3]),
		C4:           nullFloat(m.Coeffs[4]),
		TMin:         nullFloat(m.TMin),
		TMax:         nullFloat(m.TMax),
		EquationForm: nullString(m.EquationForm),
		Uncertainty:  nullString(m.Uncertainty),
		Source:       "nist",
		DocID:        sql.NullString{}, // always NULL: NIST rows have no source document
	}
}

func nullString(s string) sql.NullString {
	return sql.NullString{String: s, Valid: s != ""}
}

func nullFloat(v *float64) sql.NullFloat64 {
	if v == nil {
		return sql.NullFloat64{}
	}
	return sql.NullFloat64{Float64: *v, Valid: true}
}

// insertPrefixes are the PREFIX declarations shared by every buildInsertData
// call, matching the seed turtle's prefix set (ontology/example-flibe.ttl)
// so the emitted CURIEs resolve to identical IRIs.
const insertPrefixes = `PREFIX msr:  <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX unit: <http://qudt.org/vocab/unit/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
`

// buildInsertData is a pure, non-networked function that renders the
// additive SPARQL INSERT DATA statement for ms: catalog triples only
// (salts, constituents, compounds, measurement metadata) into
// GRAPH <urn:msr:data>. Numeric coefficients never appear here -- they are
// SQLite-only (see measurementToRow). Repeated salts/compounds/constituents
// across measurements are deduplicated by IRI so the same block is emitted
// once; under RDF set semantics repeats would be harmless, but a single
// emission keeps the output readable. The loader never emits
// hasRole/usedIn/citedIn/skos:closeMatch -- those are hand-curated seed
// facts the loader cannot derive from NIST data, and re-asserting the
// FLiBe density salt+measurement here is a set-semantics no-op against the
// seed (identical IRIs, see ontology/example-flibe.ttl).
func buildInsertData(ms []nist.Measurement) string {
	var b strings.Builder
	b.WriteString(insertPrefixes)
	b.WriteString("INSERT DATA {\nGRAPH <urn:msr:data> {\n")

	seenCompound := make(map[string]bool)
	seenSalt := make(map[string]bool)
	seenConstituent := make(map[string]bool)

	for _, m := range ms {
		for _, c := range m.Salt.Constituents {
			if c.Compound == "" || seenCompound[c.Compound] {
				continue
			}
			seenCompound[c.Compound] = true
			fmt.Fprintf(&b, "msrd:%s a msr:ChemicalCompound ; rdfs:label %s .\n", c.Compound, quoteLiteral(c.Compound))
		}

		if !seenSalt[m.Salt.IRI] {
			seenSalt[m.Salt.IRI] = true
			constituentIRIs := make([]string, 0, len(m.Salt.Constituents))
			for _, c := range m.Salt.Constituents {
				constituentIRIs = append(constituentIRIs, c.IRI)
			}
			fmt.Fprintf(&b, "%s a msr:MoltenSalt ; rdfs:label %s ; msr:hasConstituent %s .\n",
				m.Salt.IRI, quoteLiteral(m.Salt.Label), strings.Join(constituentIRIs, " , "))
		}

		for _, c := range m.Salt.Constituents {
			if seenConstituent[c.IRI] {
				continue
			}
			seenConstituent[c.IRI] = true
			b.WriteString(constituentTriples(c))
		}

		b.WriteString(measurementTriples(m))
	}

	b.WriteString("}\n}\n")
	return b.String()
}

// constituentTriples renders one Constituent: a point composition carries
// msr:moleFraction; a range composition (isotherm) carries
// msr:moleFractionMin/Max instead -- never both, so a range constituent
// never emits the plain moleFraction predicate.
func constituentTriples(c nist.Constituent) string {
	var b strings.Builder
	fmt.Fprintf(&b, "%s a msr:Constituent ; msr:ofCompound msrd:%s ;", c.IRI, c.Compound)
	switch {
	case c.MoleFraction != nil:
		fmt.Fprintf(&b, " msr:moleFraction %s .\n", formatFloat(*c.MoleFraction))
	case c.MoleFractionMin != nil && c.MoleFractionMax != nil:
		fmt.Fprintf(&b, " msr:moleFractionMin %s ; msr:moleFractionMax %s .\n",
			formatFloat(*c.MoleFractionMin), formatFloat(*c.MoleFractionMax))
	default:
		// Neither set: nothing to say about composition beyond ofCompound.
		b.WriteString("\n")
	}
	return b.String()
}

// measurementTriples renders one Measurement's catalog metadata: unit
// (full QUDT IRI), equation form, validity range (omitted where the
// pointer is nil), locator, provenance, and -- for isotherm rows -- the
// varying compositionComponent. Coefficients are deliberately absent.
func measurementTriples(m nist.Measurement) string {
	var b strings.Builder
	fmt.Fprintf(&b, "%s a msr:PropertyMeasurement ;\n", m.IRI)
	fmt.Fprintf(&b, "    msr:ofSalt %s ;\n", m.Salt.IRI)
	fmt.Fprintf(&b, "    msr:forProperty msr:%s ;\n", m.Property)
	fmt.Fprintf(&b, "    msr:hasUnit <%s> ;\n", m.UnitIRI)
	fmt.Fprintf(&b, "    msr:equationForm msr:%s ;\n", m.EquationForm)
	if m.TMin != nil {
		fmt.Fprintf(&b, "    msr:validTempMin %s ;\n", formatFloat(*m.TMin))
	}
	if m.TMax != nil {
		fmt.Fprintf(&b, "    msr:validTempMax %s ;\n", formatFloat(*m.TMax))
	}
	fmt.Fprintf(&b, "    msr:dataLocator %s ;\n", quoteLiteral(m.Locator))
	if m.CompositionComponent != "" {
		fmt.Fprintf(&b, "    msr:compositionComponent msrd:%s ;\n", m.CompositionComponent)
	}
	fmt.Fprintf(&b, "    prov:wasDerivedFrom msrd:nist-srd27 .\n")
	return b.String()
}

// quoteLiteral renders s as a Turtle/SPARQL short string literal, escaping
// backslashes and double quotes so an unexpected character in vendored
// data cannot break out of the literal.
func quoteLiteral(s string) string {
	s = strings.ReplaceAll(s, `\`, `\\`)
	s = strings.ReplaceAll(s, `"`, `\"`)
	return `"` + s + `"`
}

// formatFloat renders v as the shortest decimal that round-trips to the
// same float64 (e.g. 0.34, 800, 0.333) -- never scientific notation, so
// values like 800 read as plain "800" rather than "8e+02".
func formatFloat(v float64) string {
	return strconv.FormatFloat(v, 'f', -1, 64)
}

// printNistSummary prints the per-file, distinct-salt, and equation-form
// counts from a nist.Process run (task 6.4). Map iteration order is
// non-deterministic in Go, so both the per-file and equation-form lines
// are sorted by key for stable, greppable output.
func printNistSummary(stdout io.Writer, summary nist.Summary) {
	properties := make([]string, 0, len(summary.PerFile))
	for p := range summary.PerFile {
		properties = append(properties, p)
	}
	sort.Strings(properties)
	for _, p := range properties {
		c := summary.PerFile[p]
		fmt.Fprintf(stdout, "loader: nist: %-24s read=%d kept=%d out-of-scope=%d flagged=%d\n",
			p, c.Read, c.Kept, c.OutOfScope, c.Flagged)
	}

	fmt.Fprintf(stdout, "loader: nist: distinct canonical salts: %d\n", summary.DistinctSalts)

	forms := make([]string, 0, len(summary.EquationForms))
	for f := range summary.EquationForms {
		forms = append(forms, f)
	}
	sort.Strings(forms)
	parts := make([]string, 0, len(forms))
	for _, f := range forms {
		parts = append(parts, fmt.Sprintf("%s=%d", f, summary.EquationForms[f]))
	}
	fmt.Fprintf(stdout, "loader: nist: equation forms: %s\n", strings.Join(parts, " "))
}
