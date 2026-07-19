package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/blogem/msr-graph/internal/graph"
)

// sparqlToolDescription is the natural-language description advertised
// to the model for sparql_query (design D2, D3). It is schema-generic:
// it names no salt or property IRIs, only the grounding pattern and
// prefixes the model needs to write its own query.
const sparqlToolDescription = `Runs a SPARQL 1.1 SELECT query over the core dataset ` +
	`(the ontology, data, and vocab graphs; staging/proposal triples are never visible ` +
	`through this tool). Do NOT include a FROM or FROM NAMED clause -- the client already ` +
	`restricts the query to the core graphs and rejects any query that supplies its own ` +
	`dataset clause.

Grounding pattern -- to resolve a salt or property mention to its measurement data:
- Match the mention text against a skos:prefLabel/skos:altLabel (a salt individual also ` +
	`carries rdfs:label).
- Reach the msr:MoltenSalt individual or msr:PhysicalProperty term via skos:closeMatch. ` +
	`The link may be asserted in EITHER direction (a salt closeMatch-es its concept; a ` +
	`property concept closeMatch-es its term), so traverse it direction-agnostically with ` +
	`the property path skos:closeMatch|^skos:closeMatch.
- Read the salt's msr:PropertyMeasurement: msr:ofSalt, msr:forProperty, msr:hasUnit, ` +
	`msr:equationForm, msr:validTempMin/msr:validTempMax, msr:dataLocator, msr:citedIn, ` +
	`prov:wasDerivedFrom. msr:dataLocator is the key into the measurement_value table read ` +
	`by sql_query/run_python. A unit IRI carries an rdfs:label symbol (OPTIONAL it -- an ` +
	`external unit may lack one, and a required join would drop every row).

Declare the prefixes you use as PREFIX lines in the query itself; the tool does not inject ` +
	`them. A ready block (prov: is only needed for prov:wasDerivedFrom):
  PREFIX msr:  <https://w3id.org/msr-kg/ontology#>
  PREFIX msrd: <https://w3id.org/msr-kg/data#>
  PREFIX voc:  <https://w3id.org/msr-kg/vocab#>
  PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
  PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
  PREFIX prov: <http://www.w3.org/ns/prov#>

Worked example -- ground "FLiBe" + "density" to its measurement in one query:
  PREFIX msr:  <https://w3id.org/msr-kg/ontology#>
  PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
  PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
  SELECT DISTINCT ?salt ?prop ?dataLocator ?equationForm ?validTempMin ?validTempMax ?unit ?unitLabel WHERE {
    ?saltConcept skos:prefLabel|skos:altLabel ?sl . FILTER(LCASE(STR(?sl)) = "flibe")
    ?salt a msr:MoltenSalt ; (skos:closeMatch|^skos:closeMatch) ?saltConcept .
    ?propConcept skos:prefLabel|skos:altLabel ?pl . FILTER(LCASE(STR(?pl)) = "density")
    ?prop (skos:closeMatch|^skos:closeMatch) ?propConcept .
    ?pm a msr:PropertyMeasurement ; msr:ofSalt ?salt ; msr:forProperty ?prop ;
        msr:dataLocator ?dataLocator ; msr:equationForm ?equationForm ; msr:hasUnit ?unit .
    OPTIONAL { ?pm msr:validTempMin ?validTempMin }
    OPTIONAL { ?pm msr:validTempMax ?validTempMax }
    OPTIONAL { ?unit rdfs:label ?unitLabel }
  }
Then look up coefficients by ?dataLocator with sql_query and compute with run_python.

This tool hardcodes no salt or property identifiers; you write the grounding query.`

// sparqlToolParameters is the JSON Schema advertised for sparql_query's
// arguments: a single required "query" string.
const sparqlToolParameters = `{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "A SPARQL 1.1 SELECT query with no FROM/FROM NAMED clause."
    }
  },
  "required": ["query"]
}`

// GraphSelector is the seam sparql_query needs from internal/graph: a
// core-dataset SELECT. It is declared here, at the point of use, rather
// than imported as a broader graph.Client interface, so that the only
// method reachable through this tool is Select -- graph.Client.SelectRaw
// (the unrestricted, staging-inclusive escape hatch) is structurally
// unreachable via a GraphSelector value, satisfying the spec's
// requirement that sparql_query never expose SelectRaw.
type GraphSelector interface {
	Select(ctx context.Context, query string) (*graph.Results, error)
}

// sparqlTool implements Tool for sparql_query (design D2, D3).
type sparqlTool struct {
	sel GraphSelector
}

// NewSPARQLTool builds the sparql_query Tool backed by sel. sel is
// typically a *graph.Client, which satisfies GraphSelector via its
// Select method; because GraphSelector has no SelectRaw method, the
// tool cannot reach the staging-inclusive path regardless of what the
// model asks for.
func NewSPARQLTool(sel GraphSelector) Tool {
	return &sparqlTool{sel: sel}
}

// Spec implements Tool.
func (t *sparqlTool) Spec() ToolSpec {
	return ToolSpec{
		Name:        "sparql_query",
		Description: sparqlToolDescription,
		Parameters:  json.RawMessage(sparqlToolParameters),
	}
}

// sparqlArgs is the JSON shape of sparql_query's model-supplied
// arguments.
type sparqlArgs struct {
	Query string `json:"query"`
}

// sparqlResult is the JSON shape returned to the model: the bound
// variable names and each result row as a var-name -> value map.
type sparqlResult struct {
	Vars []string            `json:"vars"`
	Rows []map[string]string `json:"rows"`
}

// provenanceVarKinds maps a lowercase substring of a SPARQL result
// variable name to the ProvenanceEvent field it feeds. This is the
// entirety of the schema-specific knowledge in this tool: it keys off
// SPARQL variable-naming convention (e.g. a query binding ?dataLocator,
// ?citedIn, or ?doi), not off any salt or property identity, so
// grounding new data needs no change here -- only a query that binds a
// differently-named variable would need a new convention.
var provenanceVarKinds = []struct {
	substr string
	kind   string // "locator" | "cited" | "doi"
}{
	{"locator", "locator"},
	{"cited", "cited"},
	{"doi", "doi"},
	{"identifier", "doi"},
}

// Call implements Tool.
func (t *sparqlTool) Call(ctx context.Context, args string, emit Emitter) (string, error) {
	var parsed sparqlArgs
	if err := json.Unmarshal([]byte(args), &parsed); err != nil {
		return "", fmt.Errorf("sparql_query: invalid arguments JSON: %w", err)
	}
	if strings.TrimSpace(parsed.Query) == "" {
		return "", fmt.Errorf("sparql_query: missing required \"query\" argument")
	}

	results, err := t.sel.Select(ctx, parsed.Query)
	if err != nil {
		return "", fmt.Errorf("sparql_query: %w", err)
	}

	out := sparqlResult{
		Vars: results.Head.Vars,
		Rows: make([]map[string]string, 0, len(results.Results.Bindings)),
	}
	for _, binding := range results.Results.Bindings {
		row := make(map[string]string, len(binding))
		for name, b := range binding {
			row[name] = b.Value
		}
		out.Rows = append(out.Rows, row)
	}

	emitProvenance(results, emit)

	encoded, err := json.Marshal(out)
	if err != nil {
		return "", fmt.Errorf("sparql_query: encode result: %w", err)
	}
	return string(encoded), nil
}

// emitProvenance inspects results' bound variable names for the
// locator/cited/doi conventions and, if any match, emits a single
// ProvenanceEvent collecting the distinct bound values for each
// matched variable into the corresponding field. OntologyVersion is
// left empty; the agent loop stamps it (see internal/agent/events.go).
func emitProvenance(results *graph.Results, emit Emitter) {
	if emit == nil || results == nil {
		return
	}

	locatorSet := map[string]bool{}
	citedSet := map[string]bool{}
	doiSet := map[string]bool{}

	for _, varName := range results.Head.Vars {
		kind, ok := provenanceVarKind(varName)
		if !ok {
			continue
		}
		for _, binding := range results.Results.Bindings {
			b, ok := binding[varName]
			if !ok || b.Value == "" {
				continue
			}
			switch kind {
			case "locator":
				locatorSet[b.Value] = true
			case "cited":
				citedSet[b.Value] = true
			case "doi":
				doiSet[b.Value] = true
			}
		}
	}

	if len(locatorSet) == 0 && len(citedSet) == 0 && len(doiSet) == 0 {
		return
	}

	emit(Event{
		Type: EventProvenance,
		Provenance: &ProvenanceEvent{
			DataLocators: sortedKeys(locatorSet),
			CitedIn:      sortedKeys(citedSet),
			DatasetDOIs:  sortedKeys(doiSet),
		},
	})
}

// provenanceVarKind reports the provenance kind a SPARQL variable name
// maps to, matching case-insensitively on the substrings in
// provenanceVarKinds.
func provenanceVarKind(varName string) (string, bool) {
	lower := strings.ToLower(varName)
	for _, entry := range provenanceVarKinds {
		if strings.Contains(lower, entry.substr) {
			return entry.kind, true
		}
	}
	return "", false
}

// sortedKeys returns the keys of set in sorted order, for deterministic
// ProvenanceEvent output.
func sortedKeys(set map[string]bool) []string {
	out := make([]string, 0, len(set))
	for k := range set {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
