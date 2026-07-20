package nist

import (
	"encoding/json"
	"fmt"
	"os"
)

// unitEntry is one property's QUDT unit mapping as stored in the vendored
// allowlist file.
type unitEntry struct {
	QuantityKind  string `json:"quantityKind"`
	CanonicalUnit string `json:"canonicalUnit"`
	UnitCurie     string `json:"unitCurie"`
}

// allowlistFile mirrors the shape of ontology/qudt-units.json.
type allowlistFile struct {
	Properties   map[string]unitEntry `json:"properties"`
	AllowedUnits []string              `json:"allowedUnits"`
}

// UnitAllowlist is the vendored QUDT unit/quantity-kind allowlist: the
// property -> canonical-unit mapping plus the flat set of permitted unit
// IRIs. Every unit IRI Process emits is validated against it; an unknown IRI
// aborts the run (see design D7).
type UnitAllowlist struct {
	properties map[string]unitEntry
	allowed    map[string]struct{}
}

// LoadUnitAllowlist loads and parses the vendored QUDT allowlist file (e.g.
// ontology/qudt-units.json).
func LoadUnitAllowlist(path string) (*UnitAllowlist, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("nist: reading unit allowlist %s: %w", path, err)
	}
	var raw allowlistFile
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("nist: parsing unit allowlist %s: %w", path, err)
	}

	allowed := make(map[string]struct{}, len(raw.AllowedUnits))
	for _, u := range raw.AllowedUnits {
		allowed[u] = struct{}{}
	}

	return &UnitAllowlist{properties: raw.Properties, allowed: allowed}, nil
}

// UnitFor returns the canonical QUDT unit IRI and CURIE for property, and
// whether the property has a mapping at all.
func (a *UnitAllowlist) UnitFor(property string) (fullIRI, curie string, ok bool) {
	e, ok := a.properties[property]
	if !ok {
		return "", "", false
	}
	return e.CanonicalUnit, e.UnitCurie, true
}

// Validate reports an error naming fullIRI if it is not present in the
// allowlist's flat set of permitted unit IRIs.
func (a *UnitAllowlist) Validate(fullIRI string) error {
	if _, ok := a.allowed[fullIRI]; !ok {
		return fmt.Errorf("nist: unit IRI %q is not in the vendored QUDT allowlist", fullIRI)
	}
	return nil
}
