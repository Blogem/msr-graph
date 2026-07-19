package agent

// This file implements the KG-schema system prompt: a Go builder that
// serializes the ontology TBox, the SKOS controlled vocabulary, and the
// salt catalog into a canonical, byte-stable string (design D4 in
// openspec/changes/grounded-analysis-agent), plus per-request
// owl:versionInfo detection and a cache that rebuilds only on a version
// bump. The prompt is schema-only: no measurement coefficients,
// mentions, or evidence sentences ever appear here -- the agent reaches
// those exclusively through tool calls, so they stay visible in the
// trace.

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"sync"

	"github.com/blogem/msr-graph/internal/graph"
)

// SchemaSource is the read seam BuildSchemaPrompt and DetectVersion use
// to fetch schema-level bindings from the core dataset. *graph.Client
// satisfies it via Select; tests in this package drive a fake instead,
// so no test in this file contacts a live GraphDB.
type SchemaSource interface {
	Select(ctx context.Context, query string) (*graph.Results, error)
}

// sparqlPrefixes is prepended to every query issued by this file. The
// IRIs match the prefixes declared in ontology/msr.ttl and
// ontology/vocab.ttl.
const sparqlPrefixes = `PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX voc: <https://w3id.org/msr-kg/vocab#>
`

// Schema-only queries. Each is scoped to exactly the TBox/vocab/catalog
// facts the prompt needs; none of them touch msr:PropertyMeasurement or
// any other instance-level fact, so instance data (coefficients,
// mentions, evidence) never reaches the prompt builder in the first
// place.
const (
	classesQuery = sparqlPrefixes + `SELECT ?class ?label ?comment WHERE {
  ?class a owl:Class .
  OPTIONAL { ?class rdfs:label ?label }
  OPTIONAL { ?class rdfs:comment ?comment }
}`

	propertiesQuery = sparqlPrefixes + `SELECT ?property ?kind ?label ?domain ?range WHERE {
  { ?property a owl:ObjectProperty . BIND("ObjectProperty" AS ?kind) }
  UNION
  { ?property a owl:DatatypeProperty . BIND("DatatypeProperty" AS ?kind) }
  OPTIONAL { ?property rdfs:label ?label }
  OPTIONAL { ?property rdfs:domain ?domain }
  OPTIONAL { ?property rdfs:range ?range }
}`

	prefLabelsQuery = sparqlPrefixes + `SELECT ?concept ?prefLabel WHERE {
  ?concept a skos:Concept ; skos:prefLabel ?prefLabel .
}`

	altLabelsQuery = sparqlPrefixes + `SELECT ?concept ?altLabel WHERE {
  ?concept a skos:Concept ; skos:altLabel ?altLabel .
}`

	saltsQuery = sparqlPrefixes + `SELECT ?salt ?label WHERE {
  ?salt a msr:MoltenSalt .
  OPTIONAL { ?salt rdfs:label ?label }
}`

	constituentsQuery = sparqlPrefixes + `SELECT ?salt ?compound ?compoundLabel ?moleFraction WHERE {
  ?salt msr:hasConstituent ?c .
  ?c msr:ofCompound ?compound .
  OPTIONAL { ?compound rdfs:label ?compoundLabel }
  OPTIONAL { ?c msr:moleFraction ?moleFraction }
}`

	// versionQuery is the single cheap SELECT DetectVersion runs at the
	// start of every chat request (design D4).
	versionQuery = sparqlPrefixes + `SELECT ?version WHERE {
  ?ontology a owl:Ontology ; owl:versionInfo ?version .
} LIMIT 1`
)

// bindingValue returns the string value bound to key in row, or "" if
// the variable is unbound in that row (SPARQL JSON results simply omit
// unbound variables).
func bindingValue(row map[string]graph.Binding, key string) string {
	b, ok := row[key]
	if !ok {
		return ""
	}
	return b.Value
}

// schemaClass is one owl:Class fetched for the prompt.
type schemaClass struct {
	IRI     string
	Label   string
	Comment string
}

// schemaProperty is one owl:ObjectProperty or owl:DatatypeProperty
// fetched for the prompt.
type schemaProperty struct {
	IRI    string
	Kind   string // "ObjectProperty" | "DatatypeProperty"
	Label  string
	Domain string
	Range  string
}

// schemaConcept is one skos:Concept fetched for the prompt, with all of
// its altLabels collected and sorted.
type schemaConcept struct {
	IRI       string
	PrefLabel string
	AltLabels []string
}

// schemaConstituent is one compound within a schemaSalt's composition.
type schemaConstituent struct {
	Compound      string
	CompoundLabel string
	MoleFraction  string // canonically formatted, "" if absent
}

// schemaSalt is one msr:MoltenSalt individual fetched for the salt
// catalog, with its constituents collected and sorted by compound IRI.
type schemaSalt struct {
	IRI          string
	Label        string
	Constituents []schemaConstituent
}

// fetchClasses runs classesQuery and returns the results grouped by
// class IRI and sorted by IRI, independent of the order bindings came
// back in.
func fetchClasses(ctx context.Context, src SchemaSource) ([]schemaClass, error) {
	res, err := src.Select(ctx, classesQuery)
	if err != nil {
		return nil, fmt.Errorf("agent: fetch ontology classes: %w", err)
	}

	byIRI := make(map[string]*schemaClass)
	for _, row := range res.Results.Bindings {
		iri := bindingValue(row, "class")
		if iri == "" {
			continue
		}
		c, ok := byIRI[iri]
		if !ok {
			c = &schemaClass{IRI: iri}
			byIRI[iri] = c
		}
		if label := bindingValue(row, "label"); label != "" {
			c.Label = label
		}
		if comment := bindingValue(row, "comment"); comment != "" {
			c.Comment = comment
		}
	}

	classes := make([]schemaClass, 0, len(byIRI))
	for _, c := range byIRI {
		classes = append(classes, *c)
	}
	sort.Slice(classes, func(i, j int) bool { return classes[i].IRI < classes[j].IRI })
	return classes, nil
}

// fetchProperties runs propertiesQuery and returns the results grouped
// by property IRI and sorted by IRI.
func fetchProperties(ctx context.Context, src SchemaSource) ([]schemaProperty, error) {
	res, err := src.Select(ctx, propertiesQuery)
	if err != nil {
		return nil, fmt.Errorf("agent: fetch ontology properties: %w", err)
	}

	byIRI := make(map[string]*schemaProperty)
	for _, row := range res.Results.Bindings {
		iri := bindingValue(row, "property")
		if iri == "" {
			continue
		}
		p, ok := byIRI[iri]
		if !ok {
			p = &schemaProperty{IRI: iri}
			byIRI[iri] = p
		}
		if kind := bindingValue(row, "kind"); kind != "" {
			p.Kind = kind
		}
		if label := bindingValue(row, "label"); label != "" {
			p.Label = label
		}
		if domain := bindingValue(row, "domain"); domain != "" {
			p.Domain = domain
		}
		if rng := bindingValue(row, "range"); rng != "" {
			p.Range = rng
		}
	}

	properties := make([]schemaProperty, 0, len(byIRI))
	for _, p := range byIRI {
		properties = append(properties, *p)
	}
	sort.Slice(properties, func(i, j int) bool { return properties[i].IRI < properties[j].IRI })
	return properties, nil
}

// fetchConcepts runs prefLabelsQuery and altLabelsQuery and merges them
// into one sorted, deduplicated concept list. altLabels are collected
// per concept and sorted independently, so a concept's altLabel list is
// stable even if altLabelsQuery's rows come back in a different order.
func fetchConcepts(ctx context.Context, src SchemaSource) ([]schemaConcept, error) {
	prefRes, err := src.Select(ctx, prefLabelsQuery)
	if err != nil {
		return nil, fmt.Errorf("agent: fetch skos prefLabels: %w", err)
	}
	altRes, err := src.Select(ctx, altLabelsQuery)
	if err != nil {
		return nil, fmt.Errorf("agent: fetch skos altLabels: %w", err)
	}

	byIRI := make(map[string]*schemaConcept)
	for _, row := range prefRes.Results.Bindings {
		iri := bindingValue(row, "concept")
		pref := bindingValue(row, "prefLabel")
		if iri == "" {
			continue
		}
		c, ok := byIRI[iri]
		if !ok {
			c = &schemaConcept{IRI: iri}
			byIRI[iri] = c
		}
		if pref != "" {
			c.PrefLabel = pref
		}
	}
	for _, row := range altRes.Results.Bindings {
		iri := bindingValue(row, "concept")
		alt := bindingValue(row, "altLabel")
		if iri == "" || alt == "" {
			continue
		}
		c, ok := byIRI[iri]
		if !ok {
			c = &schemaConcept{IRI: iri}
			byIRI[iri] = c
		}
		c.AltLabels = append(c.AltLabels, alt)
	}

	concepts := make([]schemaConcept, 0, len(byIRI))
	for _, c := range byIRI {
		sort.Strings(c.AltLabels)
		concepts = append(concepts, *c)
	}
	sort.Slice(concepts, func(i, j int) bool { return concepts[i].IRI < concepts[j].IRI })
	return concepts, nil
}

// canonicalDecimal formats an xsd:decimal literal value canonically
// (minimal digits, no trailing zeros) so the same numeric value always
// renders identically regardless of its source lexical form (e.g.
// "0.340" and "0.34" both render as "0.34"). If raw does not parse as a
// number it is returned unchanged.
func canonicalDecimal(raw string) string {
	f, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return raw
	}
	return strconv.FormatFloat(f, 'f', -1, 64)
}

// fetchSalts runs saltsQuery and constituentsQuery and merges them into
// one sorted salt catalog. Each salt's constituents are sorted by
// compound IRI, independent of the order constituentsQuery's rows came
// back in. This is schema-level catalog data (which compounds a salt is
// made of, at what mole fraction) -- it is deliberately distinct from
// msr:PropertyMeasurement rows, which this file never queries.
func fetchSalts(ctx context.Context, src SchemaSource) ([]schemaSalt, error) {
	saltRes, err := src.Select(ctx, saltsQuery)
	if err != nil {
		return nil, fmt.Errorf("agent: fetch salt catalog: %w", err)
	}
	constRes, err := src.Select(ctx, constituentsQuery)
	if err != nil {
		return nil, fmt.Errorf("agent: fetch salt constituents: %w", err)
	}

	byIRI := make(map[string]*schemaSalt)
	for _, row := range saltRes.Results.Bindings {
		iri := bindingValue(row, "salt")
		if iri == "" {
			continue
		}
		s, ok := byIRI[iri]
		if !ok {
			s = &schemaSalt{IRI: iri}
			byIRI[iri] = s
		}
		if label := bindingValue(row, "label"); label != "" {
			s.Label = label
		}
	}
	for _, row := range constRes.Results.Bindings {
		saltIRI := bindingValue(row, "salt")
		compound := bindingValue(row, "compound")
		if saltIRI == "" || compound == "" {
			continue
		}
		s, ok := byIRI[saltIRI]
		if !ok {
			s = &schemaSalt{IRI: saltIRI}
			byIRI[saltIRI] = s
		}
		ct := schemaConstituent{
			Compound:      compound,
			CompoundLabel: bindingValue(row, "compoundLabel"),
		}
		if mf := bindingValue(row, "moleFraction"); mf != "" {
			ct.MoleFraction = canonicalDecimal(mf)
		}
		s.Constituents = append(s.Constituents, ct)
	}

	salts := make([]schemaSalt, 0, len(byIRI))
	for _, s := range byIRI {
		sort.Slice(s.Constituents, func(i, j int) bool {
			return s.Constituents[i].Compound < s.Constituents[j].Compound
		})
		salts = append(salts, *s)
	}
	sort.Slice(salts, func(i, j int) bool { return salts[i].IRI < salts[j].IRI })
	return salts, nil
}

// BuildSchemaPrompt runs the schema-only SPARQL SELECTs against src and
// serializes the ontology classes, properties, SKOS vocabulary, and salt
// catalog into a canonical system prompt. For a fixed graph state the
// output is byte-identical across calls, and independent of the order
// query bindings come back in: every set is sorted by IRI (and every
// multi-valued sub-list, such as altLabels or a salt's constituents, is
// sorted independently) after fetching (design D4, spec "Byte-stable
// KG-schema system prompt").
//
// The prompt never contains msr:PropertyMeasurement rows, coefficient
// values, mentions, or evidence sentences -- only the queries above are
// issued, and none of them touch instance-level facts (spec "Prompt
// carries schema, not instance data").
func BuildSchemaPrompt(ctx context.Context, src SchemaSource) (string, error) {
	classes, err := fetchClasses(ctx, src)
	if err != nil {
		return "", err
	}
	properties, err := fetchProperties(ctx, src)
	if err != nil {
		return "", err
	}
	concepts, err := fetchConcepts(ctx, src)
	if err != nil {
		return "", err
	}
	salts, err := fetchSalts(ctx, src)
	if err != nil {
		return "", err
	}
	return renderPrompt(classes, properties, concepts, salts), nil
}

// orDash returns s, or "-" if s is empty, for compact single-line
// rendering of an optional field.
func orDash(s string) string {
	if s == "" {
		return "-"
	}
	return s
}

// quotedList renders items as a bracketed, comma-separated list of
// double-quoted strings, e.g. `["a", "b"]`.
func quotedList(items []string) string {
	quoted := make([]string, len(items))
	for i, item := range items {
		quoted[i] = strconv.Quote(item)
	}
	return "[" + strings.Join(quoted, ", ") + "]"
}

// renderPrompt formats the fetched, pre-sorted schema sets into a
// readable, sectioned system prompt that orients the model to write
// grounding sparql_query calls (design D3: labels -> concept -> salt ->
// measurement -> locator -> coefficients).
func renderPrompt(classes []schemaClass, properties []schemaProperty, concepts []schemaConcept, salts []schemaSalt) string {
	var b strings.Builder

	b.WriteString("# MSR Knowledge Graph Schema\n\n")
	b.WriteString("This is the schema of the MSR knowledge graph: ontology classes, " +
		"properties, the SKOS controlled vocabulary, and the salt catalog, each " +
		"sorted deterministically by IRI. It contains no measurement coefficients, " +
		"mentions, or evidence -- fetch those with sparql_query/sql_query as needed. " +
		"Ground a mention via its skos:prefLabel/skos:altLabel or a salt's rdfs:label, " +
		"follow skos:closeMatch to the msr:MoltenSalt individual, then read its " +
		"msr:PropertyMeasurement.\n\n")

	b.WriteString("## Ontology classes\n\n")
	for _, c := range classes {
		b.WriteString("- " + c.IRI)
		if c.Label != "" {
			b.WriteString(fmt.Sprintf(" %q", c.Label))
		}
		if c.Comment != "" {
			b.WriteString(": " + c.Comment)
		}
		b.WriteString("\n")
	}
	b.WriteString("\n")

	b.WriteString("## Properties\n\n")
	for _, p := range properties {
		b.WriteString(fmt.Sprintf("- %s (%s)", p.IRI, p.Kind))
		if p.Label != "" {
			b.WriteString(fmt.Sprintf(" %q", p.Label))
		}
		b.WriteString(fmt.Sprintf(" domain=%s range=%s", orDash(p.Domain), orDash(p.Range)))
		b.WriteString("\n")
	}
	b.WriteString("\n")

	b.WriteString("## Vocabulary (SKOS)\n\n")
	for _, c := range concepts {
		b.WriteString(fmt.Sprintf("- %s prefLabel=%q", c.IRI, c.PrefLabel))
		if len(c.AltLabels) > 0 {
			b.WriteString(" altLabels=" + quotedList(c.AltLabels))
		}
		b.WriteString("\n")
	}
	b.WriteString("\n")

	b.WriteString("## Salt catalog\n\n")
	for _, s := range salts {
		b.WriteString("- " + s.IRI)
		if s.Label != "" {
			b.WriteString(fmt.Sprintf(" %q", s.Label))
		}
		if len(s.Constituents) > 0 {
			parts := make([]string, len(s.Constituents))
			for i, ct := range s.Constituents {
				name := ct.CompoundLabel
				if name == "" {
					name = ct.Compound
				}
				if ct.MoleFraction != "" {
					parts[i] = fmt.Sprintf("%s=%s", name, ct.MoleFraction)
				} else {
					parts[i] = name
				}
			}
			b.WriteString(" constituents=[" + strings.Join(parts, ", ") + "]")
		}
		b.WriteString("\n")
	}

	return b.String()
}

// DetectVersion runs the single owl:versionInfo SELECT the server issues
// at the start of every chat request (design D4). The returned value is
// also what the provenance event reports as the "ontology version used".
func DetectVersion(ctx context.Context, src SchemaSource) (string, error) {
	res, err := src.Select(ctx, versionQuery)
	if err != nil {
		return "", fmt.Errorf("agent: detect ontology version: %w", err)
	}
	for _, row := range res.Results.Bindings {
		if v := bindingValue(row, "version"); v != "" {
			return v, nil
		}
	}
	return "", fmt.Errorf("agent: no owl:versionInfo found for the ontology")
}

// PromptCache caches the built system prompt and rebuilds it only when
// DetectVersion reports a different owl:versionInfo than the cached
// build, so a live server picks up ontology approvals/restores (which
// have no push signal) with one cheap SELECT per chat request instead of
// rebuilding on every turn (design D4). It is safe for concurrent use by
// multiple in-flight chat requests.
type PromptCache struct {
	src SchemaSource

	mu      sync.Mutex
	built   bool
	version string
	prompt  string
}

// NewPromptCache builds an empty PromptCache reading schema state from
// src. The first Get call always builds the prompt.
func NewPromptCache(src SchemaSource) *PromptCache {
	return &PromptCache{src: src}
}

// Get detects the current owl:versionInfo and returns the cached prompt
// if it matches the version the cache was last built with; otherwise it
// rebuilds via BuildSchemaPrompt, caches the result, and returns it. The
// returned version is always the one just detected, whether or not a
// rebuild happened, so callers can report it as the provenance event's
// "ontology version used".
func (c *PromptCache) Get(ctx context.Context) (prompt string, version string, err error) {
	version, err = DetectVersion(ctx, c.src)
	if err != nil {
		return "", "", err
	}

	c.mu.Lock()
	defer c.mu.Unlock()

	if c.built && c.version == version {
		return c.prompt, version, nil
	}

	prompt, err = BuildSchemaPrompt(ctx, c.src)
	if err != nil {
		return "", "", err
	}
	c.prompt = prompt
	c.version = version
	c.built = true
	return c.prompt, version, nil
}
