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
	"time"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/nist"
	"github.com/blogem/msr-graph/internal/store"
)

// ontologyVersion is the loader's own version, recorded via
// owl:versionInfo on both the stable per-pipeline Activity in urn:msr:data
// and the per-run Activity written into urn:msr:provenance. Bump this
// alongside releases that change the loader's emitted triples.
const ontologyVersion = "0.3.0"

// qudtAllowlistFile is the vendored QUDT unit/quantity-kind allowlist,
// resolved relative to config.ontologyDir (it lives alongside the seed
// turtle files, not under the NIST data directory).
const qudtAllowlistFile = "qudt-units.json"

// runNist implements `loader nist`: it runs the pure internal/nist
// transformation core over the vendored CSVs (task contract step 3),
// upserts the resulting rows into SQLite (numeric coefficients live only
// there), sends an additive SPARQL INSERT DATA of the catalog triples into
// urn:msr:data, writes this run's per-run Activity and per-fact
// generation-lineage edges into urn:msr:provenance, and prints a run
// summary.
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

	// Both client.Update calls below may fail because SHACL rejected the
	// write (design D5, task 5.1): client.Update returns a
	// *graph.ValidationError in that case (still wrapped by %w here, so
	// errors.As still finds it through this fmt.Errorf chain). main.go's
	// reportError distinguishes that from a transport/5xx failure at the
	// CLI's error-reporting boundary, for every subcommand uniformly.
	// Note for the extraction (Python) writers: they should make the same
	// distinction (validation rejection vs. transport/5xx) when they
	// report their own GraphDB write failures.
	client := graph.New(cfg.graphDBURL, cfg.graphDBRepo, nil)
	sparql, factIRIs := buildInsertData(measurements, ontologyVersion)
	if err := client.Update(ctx, sparql); err != nil {
		return fmt.Errorf("nist: inserting catalog triples into %s: %w", graph.Data, err)
	}

	provenanceSPARQL := buildProvenanceData(time.Now().UTC(), ontologyVersion, factIRIs)
	if err := client.Update(ctx, provenanceSPARQL); err != nil {
		return fmt.Errorf("nist: writing provenance activity + lineage into %s: %w", graph.Provenance, err)
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

// Provenance constants. nistDatasetIRI is the loader's deterministic IRI
// for the NIST SRD-27 dataset -- buildInsertData defines this node itself
// (the seed that used to define it is gone, see design D3), and every
// measurement/catalog individual's prov:wasDerivedFrom points at it.
// nistDatasetDOI is that dataset's real external identifier.
// loaderActivityIRI is the deterministic per-pipeline Activity IRI every
// loader-emitted individual references via prov:wasGeneratedBy (design
// D1/D2) -- deterministic so the edge in urn:msr:data re-asserts as a
// set-semantics no-op across runs; buildInsertData also types this IRI
// once in urn:msr:data (no timestamps, still idempotent). The wall-clock,
// per-run Activity is a distinct, per-run IRI (urn:msr:run:loader/<ts>)
// written into urn:msr:provenance by buildProvenanceData -- see design D1.
const (
	nistDatasetIRI    = "msrd:nist-srd27"
	nistDatasetDOI    = "doi:10.18434/mds2-2298"
	loaderActivityIRI = "msrd:activity-loader-nist"
)

// insertPrefixes are the PREFIX declarations shared by every buildInsertData
// call. These fix the loader's own deterministic-IRI-minting contract
// (msr/msrd/unit/prov/owl/rdfs/dcterms), independent of any hand-curated data.
const insertPrefixes = `PREFIX msr:  <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX unit: <http://qudt.org/vocab/unit/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX dcterms: <http://purl.org/dc/terms/>
`

// buildInsertData is a pure, non-networked function that renders the
// additive SPARQL INSERT DATA statement for ms: catalog triples only
// (salts, constituents, compounds, measurement metadata) into
// GRAPH <urn:msr:data>. Numeric coefficients never appear here -- they are
// SQLite-only (see measurementToRow). Repeated salts/compounds/constituents
// across measurements are deduplicated by IRI so the same block is emitted
// once; under RDF set semantics repeats would be harmless, but a single
// emission keeps the output readable. The loader never emits
// hasRole/usedIn/citedIn/skos:closeMatch -- those are not derivable from
// NIST data; the loader mints deterministic IRIs from salt composition
// (see internal/nist), so re-running against unchanged input data is a
// set-semantics no-op (identical IRIs, identical triples).
//
// The loader is now the sole source of the msrd:nist-srd27 msr:Dataset
// node (design D3: the seed that used to define it is gone), so this
// function also emits that node -- with its DOI -- exactly once,
// regardless of how many measurements follow. It is a derivation root: it
// carries its external id (dcterms:identifier), never a wasDerivedFrom.
// Every emitted MoltenSalt/Constituent/ChemicalCompound/PropertyMeasurement
// additionally carries prov:wasGeneratedBy the stable, deterministic
// loaderActivityIRI and prov:wasDerivedFrom this Dataset node, so all
// instance data the loader asserts is provenanced, not just measurements.
// This function also types loaderActivityIRI itself, exactly once, as
// `a prov:Activity ; prov:wasAssociatedWith <agent...> ; owl:versionInfo
// "<version>"` -- deliberately with no timestamps, so this typing
// re-asserts as a set-semantics no-op across runs (design D1/D4). The
// wall-clock per-run Activity record lives separately, in
// urn:msr:provenance (see buildProvenanceData).
//
// buildInsertData additionally returns the deduped, ordered slice of every
// fact IRI it emits a block for (Dataset, each ChemicalCompound,
// MoltenSalt, Constituent, and PropertyMeasurement) so the caller can pass
// that exact set into buildProvenanceData -- guaranteeing the per-run
// generation-lineage edges cover precisely the facts this call asserted,
// with no separate/divergent dedup logic.
func buildInsertData(ms []nist.Measurement, version string) (string, []string) {
	var b strings.Builder
	b.WriteString(insertPrefixes)
	b.WriteString("INSERT DATA {\nGRAPH <urn:msr:data> {\n")

	fmt.Fprintf(&b, "%s a msr:Dataset ; dcterms:identifier %s .\n", nistDatasetIRI, quoteLiteral(nistDatasetDOI))
	fmt.Fprintf(&b, "%s a prov:Activity ; prov:wasAssociatedWith <agent:loader@%s> ; owl:versionInfo %s .\n",
		loaderActivityIRI, version, quoteLiteral(version))

	factIRIs := make([]string, 0, len(ms)*4+1)
	factIRIs = append(factIRIs, nistDatasetIRI)

	seenCompound := make(map[string]bool)
	seenSalt := make(map[string]bool)
	seenConstituent := make(map[string]bool)
	seenMeasurement := make(map[string]bool)

	for _, m := range ms {
		if seenMeasurement[m.IRI] {
			// Defensive: a repeated measurement IRI should never occur once
			// nist.Process disambiguates colliding locators, but never emit
			// two blocks for the same subject if it somehow does.
			continue
		}
		seenMeasurement[m.IRI] = true

		for _, c := range m.Salt.Constituents {
			if c.Compound == "" || seenCompound[c.Compound] {
				continue
			}
			seenCompound[c.Compound] = true
			compoundIRI := "msrd:" + c.Compound
			fmt.Fprintf(&b, "%s a msr:ChemicalCompound ; rdfs:label %s ; prov:wasGeneratedBy %s ; prov:wasDerivedFrom %s .\n",
				compoundIRI, quoteLiteral(c.Compound), loaderActivityIRI, nistDatasetIRI)
			factIRIs = append(factIRIs, compoundIRI)
		}

		if !seenSalt[m.Salt.IRI] {
			seenSalt[m.Salt.IRI] = true
			constituentIRIs := make([]string, 0, len(m.Salt.Constituents))
			for _, c := range m.Salt.Constituents {
				constituentIRIs = append(constituentIRIs, c.IRI)
			}
			fmt.Fprintf(&b, "%s a msr:MoltenSalt ; rdfs:label %s ; msr:hasConstituent %s ; prov:wasGeneratedBy %s ; prov:wasDerivedFrom %s .\n",
				m.Salt.IRI, quoteLiteral(m.Salt.Label), strings.Join(constituentIRIs, " , "), loaderActivityIRI, nistDatasetIRI)
			factIRIs = append(factIRIs, m.Salt.IRI)
		}

		for _, c := range m.Salt.Constituents {
			if seenConstituent[c.IRI] {
				continue
			}
			seenConstituent[c.IRI] = true
			b.WriteString(constituentTriples(c))
			factIRIs = append(factIRIs, c.IRI)
		}

		b.WriteString(measurementTriples(m))
		factIRIs = append(factIRIs, m.IRI)
	}

	b.WriteString("}\n}\n")
	return b.String(), factIRIs
}

// constituentTriples renders one Constituent: a point composition carries
// msr:moleFraction; a range composition (isotherm) carries
// msr:moleFractionMin/Max instead -- never both, so a range constituent
// never emits the plain moleFraction predicate. Every constituent also
// carries prov:wasGeneratedBy/wasDerivedFrom (task 2.3b): it is asserted
// data, not just measurements.
func constituentTriples(c nist.Constituent) string {
	var b strings.Builder
	fmt.Fprintf(&b, "%s a msr:Constituent ; msr:ofCompound msrd:%s ;", c.IRI, c.Compound)
	switch {
	case c.MoleFraction != nil:
		fmt.Fprintf(&b, " msr:moleFraction %s ;", formatFloat(*c.MoleFraction))
	case c.MoleFractionMin != nil && c.MoleFractionMax != nil:
		fmt.Fprintf(&b, " msr:moleFractionMin %s ; msr:moleFractionMax %s ;",
			formatFloat(*c.MoleFractionMin), formatFloat(*c.MoleFractionMax))
	default:
		// Neither set: nothing to say about composition beyond ofCompound.
	}
	fmt.Fprintf(&b, " prov:wasGeneratedBy %s ; prov:wasDerivedFrom %s .\n", loaderActivityIRI, nistDatasetIRI)
	return b.String()
}

// measurementTriples renders one Measurement's catalog metadata: unit
// (full QUDT IRI), equation form, validity range (omitted where the
// pointer is nil), locator, provenance, and -- for isotherm rows -- the
// varying compositionComponent. Coefficients are deliberately absent.
// Provenance is prov:wasGeneratedBy the stable, deterministic
// loaderActivityIRI plus prov:wasDerivedFrom the NIST dataset -- no
// msr:citedIn, since NIST SRD-27 has no per-row citation to assert
// truthfully (design D3).
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
	fmt.Fprintf(&b, "    prov:wasGeneratedBy %s ;\n", loaderActivityIRI)
	fmt.Fprintf(&b, "    prov:wasDerivedFrom %s .\n", nistDatasetIRI)
	return b.String()
}

// buildProvenanceData is a pure, non-networked function that renders the
// additive SPARQL INSERT DATA statement recording this loader run's
// per-run lineage into the single, append-only GRAPH <urn:msr:provenance>
// (design D1/D2/D4). Unlike buildInsertData, this write is intentionally
// per-run, not idempotent: every invocation with a distinct ts mints a
// distinct per-run Activity node <urn:msr:run:loader/{ts}> (a node, not a
// graph name -- design D2), so re-running the loader against unchanged
// input still leaves an audit trail of "when did this run happen" rather
// than being collapsed away by set semantics. The caller supplies ts
// explicitly (rather than this function calling time.Now()) so it stays a
// pure, deterministically-testable function of its inputs.
//
// factIRIs is the exact deduped set buildInsertData emitted a block for
// (Dataset, ChemicalCompound, MoltenSalt, Constituent,
// PropertyMeasurement -- see its doc comment). For every IRI in factIRIs,
// this function writes one <factIRI> prov:wasGeneratedBy <run> edge --
// "touched" semantics (design D3): the edge is written whether or not the
// fact already existed in urn:msr:data, so a fact asserted by N runs
// accumulates N generation edges here, giving full per-run lineage
// without any read-before-write. Edges are emitted in the same order as
// factIRIs (the deduped emission order from buildInsertData), so the
// output is deterministic for a fixed ts and input, never dependent on
// map iteration order.
//
// This function no longer writes a urn:msr:src:* graph: the
// msrd:nist-srd27 msr:Dataset node is self-contained in urn:msr:data
// (buildInsertData emits it), so a separate source-audit copy was
// redundant (design D2) and is dropped, not moved.
func buildProvenanceData(ts time.Time, version string, factIRIs []string) string {
	tsStr := ts.UTC().Format(time.RFC3339)
	runIRI := fmt.Sprintf("<urn:msr:run:loader/%s>", tsStr)

	var b strings.Builder
	b.WriteString(`PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
`)
	b.WriteString("INSERT DATA {\nGRAPH <urn:msr:provenance> {\n")

	fmt.Fprintf(&b, "%s a prov:Activity ;\n", runIRI)
	fmt.Fprintf(&b, "    prov:wasAssociatedWith <agent:loader@%s> ;\n", version)
	fmt.Fprintf(&b, "    prov:startedAtTime \"%s\"^^xsd:dateTime ;\n", tsStr)
	fmt.Fprintf(&b, "    prov:endedAtTime   \"%s\"^^xsd:dateTime ;\n", tsStr)
	fmt.Fprintf(&b, "    owl:versionInfo %s .\n", quoteLiteral(version))

	for _, iri := range factIRIs {
		fmt.Fprintf(&b, "%s prov:wasGeneratedBy %s .\n", iri, runIRI)
	}

	b.WriteString("}\n}\n")
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
// same float64 (e.g. 0.34, 800.0, 0.333) -- never scientific notation, so
// values like 800 read as "800.0" rather than "8e+02". Whole numbers always
// get an explicit ".0" so the emitted literal parses as xsd:decimal, never
// xsd:integer: under RDF set semantics 800 (xsd:integer) is a distinct
// triple object from 800.0 (xsd:decimal) -- without this, re-running the
// loader against unchanged input would add a second validTempMin triple
// instead of being the intended set-semantics no-op.
func formatFloat(v float64) string {
	s := strconv.FormatFloat(v, 'f', -1, 64)
	if !strings.ContainsAny(s, ".eE") {
		s += ".0"
	}
	return s
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
