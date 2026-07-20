package nist

import (
	"fmt"
	"strings"
)

// slugify turns a canonical string or locator into the hyphen-only slug used
// to mint salt and measurement IRIs: ' ', '/', '#', '|', '=', and '@' become
// '-', repeated hyphens collapse to one, and leading/trailing hyphens are
// trimmed. '@' is included so a disambiguated locator (see
// disambiguateLocators in process.go, which appends "@<tmin>" to break
// collisions between multiple measurements for the same property+salt)
// still slugifies to a valid msrd: CURIE local name.
func slugify(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch r {
		case ' ', '/', '#', '|', '=', '@':
			b.WriteByte('-')
		default:
			b.WriteRune(r)
		}
	}
	slug := b.String()
	for strings.Contains(slug, "--") {
		slug = strings.ReplaceAll(slug, "--", "-")
	}
	return strings.Trim(slug, "-")
}

// splitCanonical splits a canonical salt string "{formula} | {composition}"
// into its formula and composition parts.
func splitCanonical(canonical string) (formula, compositionPart string) {
	parts := strings.SplitN(canonical, " | ", 2)
	if len(parts) != 2 {
		return canonical, ""
	}
	return parts[0], parts[1]
}

// splitRangeComposition splits a range-salt composition part
// "{varyComponent} {lo}-{hi}" into the varying component name and the
// lo-hi range string.
func splitRangeComposition(compositionPart string) (varyComponent, rangePart string) {
	parts := strings.SplitN(compositionPart, " ", 2)
	if len(parts) != 2 {
		return "", compositionPart
	}
	return parts[0], parts[1]
}

// buildLocator mints the contract locator form for a measurement of the
// given property on salt: point salts get
// "nist-srd27/{property}#{formula}|{v1}-{v2}"; range (isotherm) salts get
// "nist-srd27/{property}#{formula}|{varyComponent}={lo}-{hi}".
func buildLocator(property string, salt Salt) string {
	formula, compositionPart := splitCanonical(salt.Canonical)
	if salt.IsRange {
		varyComponent, rangePart := splitRangeComposition(compositionPart)
		return fmt.Sprintf("nist-srd27/%s#%s|%s=%s", property, formula, varyComponent, rangePart)
	}
	return fmt.Sprintf("nist-srd27/%s#%s|%s", property, formula, compositionPart)
}

// buildMeasurementIRI mints the measurement IRI from its locator:
// "msrd:m-{locator-slug}".
func buildMeasurementIRI(locator string) string {
	return "msrd:m-" + slugify(locator)
}

// compositionComponent returns the varying compound formula for a
// range-composition (isotherm) salt, or "" for a point salt.
func compositionComponent(salt Salt) string {
	if !salt.IsRange {
		return ""
	}
	_, compositionPart := splitCanonical(salt.Canonical)
	varyComponent, _ := splitRangeComposition(compositionPart)
	return varyComponent
}
