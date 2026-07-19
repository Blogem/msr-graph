package nist_test

// Unit tests for the vendored QUDT unit allowlist guard (task 8.5).
// Grounded in openspec/changes/load-nist-structured-data/design.md D7 and
// specs/qudt-unit-allowlist/spec.md: the allowlist is the committed file
// ontology/qudt-units.json (property -> canonical unit mapping, plus the
// flat list of permitted unit IRIs), and every emitted unit IRI must
// validate against it.

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/nist"
)

const wantDensityUnitIRI = "http://qudt.org/vocab/unit/GM-PER-CentiM3"
const wantDensityUnitCurie = "unit:GM-PER-CentiM3"

func loadAllowlistOrSkip(t *testing.T) *nist.UnitAllowlist {
	t.Helper()
	path := filepath.Join("..", "..", "ontology", "qudt-units.json")
	if _, err := os.Stat(path); err != nil {
		if os.IsNotExist(err) {
			t.Skipf("allowlist not present yet at %s (vendored by task 1.3): %v", path, err)
		}
	}
	allowlist, err := nist.LoadUnitAllowlist(path)
	if err != nil {
		t.Fatalf("LoadUnitAllowlist(%s): %v", path, err)
	}
	return allowlist
}

func TestUnitAllowlist_UnitForResolvesDensity(t *testing.T) {
	allowlist := loadAllowlistOrSkip(t)

	fullIRI, curie, ok := allowlist.UnitFor(nist.PropDensity)
	if !ok {
		t.Fatalf("UnitFor(%q) = ok=false, want true", nist.PropDensity)
	}
	if fullIRI != wantDensityUnitIRI {
		t.Errorf("UnitFor(%q) fullIRI = %q, want %q", nist.PropDensity, fullIRI, wantDensityUnitIRI)
	}
	if curie != wantDensityUnitCurie {
		t.Errorf("UnitFor(%q) curie = %q, want %q", nist.PropDensity, curie, wantDensityUnitCurie)
	}
}

func TestUnitAllowlist_ValidateKnownIRIPasses(t *testing.T) {
	allowlist := loadAllowlistOrSkip(t)

	if err := allowlist.Validate(wantDensityUnitIRI); err != nil {
		t.Errorf("Validate(%q): unexpected error: %v", wantDensityUnitIRI, err)
	}
}

func TestUnitAllowlist_ValidateUnknownIRIAborts(t *testing.T) {
	allowlist := loadAllowlistOrSkip(t)

	const bogus = "http://qudt.org/vocab/unit/BOGUS"
	err := allowlist.Validate(bogus)
	if err == nil {
		t.Fatalf("Validate(%q): expected an error for an unknown unit IRI, got nil", bogus)
	}
	if !strings.Contains(err.Error(), bogus) {
		t.Errorf("Validate(%q) error = %q, want it to contain the offending IRI %q", bogus, err.Error(), bogus)
	}
}
