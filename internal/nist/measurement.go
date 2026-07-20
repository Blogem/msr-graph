package nist

import (
	"fmt"
	"strconv"
	"strings"
)

// Measurement is one canonicalized, typed NIST property measurement, ready
// to write to SQLite (coefficients) and GraphDB (catalog triples).
type Measurement struct {
	Salt                 Salt
	Property             string      // one of the Prop* constants
	EquationForm         string      // msr EquationForm local name: "Linear","Arrhenius","Isotherm3",...
	UnitIRI              string      // full QUDT IRI, e.g. "http://qudt.org/vocab/unit/GM-PER-CentiM3"
	UnitCurie            string      // "unit:GM-PER-CentiM3"
	Coeffs               [5]*float64 // c0..c4 (nil where the source column is empty)
	TMin, TMax           *float64    // both equal for DP / isotherm (single T)
	Uncertainty          string
	Locator              string // "nist-srd27/{property}#{canonical-salt-locatorform}"
	IRI                  string // measurement IRI "msrd:m-..."
	CompositionComponent string // isotherms only: the varying compound formula (e.g. "ZrF4"); "" otherwise
}

// parseFloatPtr parses a raw column value into a *float64, treating a blank
// (whitespace-only) string as an absent value (nil), never an error.
func parseFloatPtr(s string) (*float64, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil, nil
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return nil, err
	}
	return &v, nil
}

// parseFloatPtrStripK is parseFloatPtr, but first strips a trailing "K"/"k"
// suffix (Kelvin marker). DP rows carry temperature as e.g. "1073K" in the
// Data 2 column; no other column in the vendored files carries this suffix,
// so it is safe to strip it unconditionally for every Data 1..5 value.
func parseFloatPtrStripK(s string) (*float64, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil, nil
	}
	s = strings.TrimSuffix(s, "K")
	s = strings.TrimSuffix(s, "k")
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return nil, err
	}
	return &v, nil
}

// buildMeasurement maps one filtered, canonicalized row to a Measurement:
// coefficients from Data 1..5 (with DP's Data 2 K-suffix stripped),
// TMin/TMax per the DP / isotherm / general-form dispatch, the resolved +
// validated unit IRI, and the minted locator + measurement IRI.
func buildMeasurement(row rawRow, salt Salt, form, formCode, property string, units *UnitAllowlist) (Measurement, error) {
	dataCols := [5]string{row.Data1, row.Data2, row.Data3, row.Data4, row.Data5}
	var coeffs [5]*float64
	for i, s := range dataCols {
		v, err := parseFloatPtrStripK(s)
		if err != nil {
			return Measurement{}, fmt.Errorf("nist: invalid Data %d value %q: %w", i+1, s, err)
		}
		coeffs[i] = v
	}

	var tMin, tMax *float64
	switch {
	case formCode == "DP":
		// c0 = value (Data 1), c1 = temperature (Data 2, K stripped);
		// TMin = TMax = that temperature.
		tMin = coeffs[1]
		tMax = coeffs[1]
	case isIsothermCode(formCode):
		// Single temperature in T min; T max column is empty on isotherm rows.
		v, err := parseFloatPtr(row.TMin)
		if err != nil {
			return Measurement{}, fmt.Errorf("nist: invalid T min value %q: %w", row.TMin, err)
		}
		tMin = v
		tMax = v
	default:
		vMin, err := parseFloatPtr(row.TMin)
		if err != nil {
			return Measurement{}, fmt.Errorf("nist: invalid T min value %q: %w", row.TMin, err)
		}
		vMax, err := parseFloatPtr(row.TMax)
		if err != nil {
			return Measurement{}, fmt.Errorf("nist: invalid T max value %q: %w", row.TMax, err)
		}
		tMin, tMax = vMin, vMax
	}

	unitIRI, unitCurie, ok := units.UnitFor(property)
	if !ok {
		return Measurement{}, fmt.Errorf("nist: no unit mapping for property %q", property)
	}
	if err := units.Validate(unitIRI); err != nil {
		return Measurement{}, err
	}

	locator := buildLocator(property, salt)
	iri := buildMeasurementIRI(locator)

	return Measurement{
		Salt:                 salt,
		Property:             property,
		EquationForm:         form,
		UnitIRI:              unitIRI,
		UnitCurie:            unitCurie,
		Coeffs:               coeffs,
		TMin:                 tMin,
		TMax:                 tMax,
		Uncertainty:          row.Uncertainty,
		Locator:              locator,
		IRI:                  iri,
		CompositionComponent: compositionComponent(salt),
	}, nil
}
