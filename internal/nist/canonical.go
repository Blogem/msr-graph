package nist

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

// positionalSumTolerance is the ±2.0 mol% tolerance a positional
// composition's values may deviate from summing to 100, per D4 /
// salt-canonicalization spec. It admits the real 26.04-72.96 row (sums to
// 99.0) without misclassifying malformed rows.
const positionalSumTolerance = 2.0

// Constituent is one compound's share of a Salt, either a single mole
// fraction (point composition) or a min/max range (isotherm composition).
type Constituent struct {
	Compound        string   // formula token, e.g. "BeF2"
	IRI             string   // "{salt-iri}-c-{compound}"
	MoleFraction    *float64 // set for positional single composition (fraction, 0.34)
	MoleFractionMin *float64 // set for range composition
	MoleFractionMax *float64
}

// Salt is a canonical salt (point OR range composition).
type Salt struct {
	Canonical    string        // "BeF2-LiF | 34.0-66.0" (point) or "KF-ZrF4 | ZrF4 0.0-33.3" (range)
	IRI          string        // "msrd:salt-BeF2-LiF-34.0-66.0"
	Label        string        // "BeF2-LiF (34.0-66.0 mol%)"
	Components   []string      // byte-sorted formula tokens, e.g. ["BeF2","LiF"]
	Constituents []Constituent
	IsRange      bool
}

// Canonicalize parses a raw Salt token + Composition-range string + equation-form
// CODE into a canonical Salt. The form code decides interpretation: I1-I4 => range
// isotherm; everything else => positional single composition.
func Canonicalize(saltToken, compositionRange, formCode string) (Salt, error) {
	components := strings.Split(strings.TrimSpace(saltToken), "-")
	if len(components) == 0 || components[0] == "" {
		return Salt{}, fmt.Errorf("nist: empty salt token %q", saltToken)
	}
	for _, c := range components {
		if strings.TrimSpace(c) == "" {
			return Salt{}, fmt.Errorf("nist: salt token %q has an empty component", saltToken)
		}
	}

	if isIsothermCode(formCode) {
		return canonicalizeRange(components, compositionRange)
	}
	return canonicalizePositional(components, compositionRange)
}

// sortedOrder returns the permutation of indices into components that puts
// them in byte-wise ascending order (plain Go string comparison, no locale
// collation).
func sortedOrder(components []string) []int {
	order := make([]int, len(components))
	for i := range order {
		order[i] = i
	}
	sort.Slice(order, func(i, j int) bool { return components[order[i]] < components[order[j]] })
	return order
}

func floatPtr(v float64) *float64 { return &v }

func canonicalizePositional(components []string, compositionRange string) (Salt, error) {
	rawValues := strings.Split(strings.TrimSpace(compositionRange), "-")
	if len(rawValues) != len(components) {
		return Salt{}, fmt.Errorf("nist: composition %q has %d value(s), expected %d for salt %q",
			compositionRange, len(rawValues), len(components), strings.Join(components, "-"))
	}

	values := make([]float64, len(rawValues))
	sum := 0.0
	for i, rv := range rawValues {
		v, err := strconv.ParseFloat(strings.TrimSpace(rv), 64)
		if err != nil {
			return Salt{}, fmt.Errorf("nist: invalid composition value %q in %q: %w", rv, compositionRange, err)
		}
		values[i] = v
		sum += v
	}
	if math.Abs(sum-100.0) > positionalSumTolerance {
		return Salt{}, fmt.Errorf("nist: composition %q sums to %.4g, outside ±%.1f mol%% of 100",
			compositionRange, sum, positionalSumTolerance)
	}

	order := sortedOrder(components)
	sortedComponents := make([]string, len(components))
	sortedValues := make([]float64, len(components))
	for i, idx := range order {
		sortedComponents[i] = components[idx]
		sortedValues[i] = values[idx]
	}

	formattedValues := make([]string, len(sortedValues))
	for i, v := range sortedValues {
		formattedValues[i] = fmt.Sprintf("%.1f", v)
	}

	formula := strings.Join(sortedComponents, "-")
	compositionStr := strings.Join(formattedValues, "-")
	canonical := formula + " | " + compositionStr

	saltIRI := "msrd:salt-" + slugify(canonical)
	label := fmt.Sprintf("%s (%s mol%%)", formula, compositionStr)

	constituents := make([]Constituent, len(sortedComponents))
	for i, comp := range sortedComponents {
		// Recompute the fraction from the formatted (one-decimal) value so
		// the constituent's mole fraction is consistent with the canonical
		// string, rather than an unrounded input value.
		rounded, err := strconv.ParseFloat(formattedValues[i], 64)
		if err != nil {
			return Salt{}, fmt.Errorf("nist: internal: reformatting %q: %w", formattedValues[i], err)
		}
		frac := rounded / 100.0
		constituents[i] = Constituent{
			Compound:     comp,
			IRI:          saltIRI + "-c-" + comp,
			MoleFraction: floatPtr(frac),
		}
	}

	return Salt{
		Canonical:    canonical,
		IRI:          saltIRI,
		Label:        label,
		Components:   sortedComponents,
		Constituents: constituents,
		IsRange:      false,
	}, nil
}

func canonicalizeRange(components []string, compositionRange string) (Salt, error) {
	if len(components) != 2 {
		return Salt{}, fmt.Errorf("nist: isotherm range salts must have exactly 2 components, got %d (%v)",
			len(components), components)
	}

	fields := strings.Fields(strings.TrimSpace(compositionRange))
	if len(fields) != 2 {
		return Salt{}, fmt.Errorf("nist: isotherm composition %q must be \"lo-hi COMPONENT\"", compositionRange)
	}
	rangePart, varyComponent := fields[0], fields[1]

	rangeValues := strings.Split(rangePart, "-")
	if len(rangeValues) != 2 {
		return Salt{}, fmt.Errorf("nist: isotherm composition range %q must be \"lo-hi\"", rangePart)
	}
	lo, err := strconv.ParseFloat(strings.TrimSpace(rangeValues[0]), 64)
	if err != nil {
		return Salt{}, fmt.Errorf("nist: invalid isotherm range low value %q: %w", rangeValues[0], err)
	}
	hi, err := strconv.ParseFloat(strings.TrimSpace(rangeValues[1]), 64)
	if err != nil {
		return Salt{}, fmt.Errorf("nist: invalid isotherm range high value %q: %w", rangeValues[1], err)
	}

	found := false
	for _, c := range components {
		if c == varyComponent {
			found = true
			break
		}
	}
	if !found {
		return Salt{}, fmt.Errorf("nist: varying component %q not found among salt components %v", varyComponent, components)
	}

	order := sortedOrder(components)
	sortedComponents := make([]string, len(components))
	for i, idx := range order {
		sortedComponents[i] = components[idx]
	}

	formula := strings.Join(sortedComponents, "-")
	loStr := fmt.Sprintf("%.1f", lo)
	hiStr := fmt.Sprintf("%.1f", hi)
	canonical := fmt.Sprintf("%s | %s %s-%s", formula, varyComponent, loStr, hiStr)

	saltIRI := "msrd:salt-" + slugify(canonical)
	label := fmt.Sprintf("%s (%s %s-%s mol%%)", formula, varyComponent, loStr, hiStr)

	loFrac, err := strconv.ParseFloat(loStr, 64)
	if err != nil {
		return Salt{}, fmt.Errorf("nist: internal: reformatting %q: %w", loStr, err)
	}
	hiFrac, err := strconv.ParseFloat(hiStr, 64)
	if err != nil {
		return Salt{}, fmt.Errorf("nist: internal: reformatting %q: %w", hiStr, err)
	}
	loFrac /= 100.0
	hiFrac /= 100.0
	complementLo := 1.0 - hiFrac
	complementHi := 1.0 - loFrac

	constituents := make([]Constituent, len(sortedComponents))
	for i, comp := range sortedComponents {
		if comp == varyComponent {
			constituents[i] = Constituent{
				Compound:        comp,
				IRI:             saltIRI + "-c-" + comp,
				MoleFractionMin: floatPtr(loFrac),
				MoleFractionMax: floatPtr(hiFrac),
			}
		} else {
			constituents[i] = Constituent{
				Compound:        comp,
				IRI:             saltIRI + "-c-" + comp,
				MoleFractionMin: floatPtr(complementLo),
				MoleFractionMax: floatPtr(complementHi),
			}
		}
	}

	return Salt{
		Canonical:    canonical,
		IRI:          saltIRI,
		Label:        label,
		Components:   sortedComponents,
		Constituents: constituents,
		IsRange:      true,
	}, nil
}
