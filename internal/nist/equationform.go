package nist

import "fmt"

// equationForms maps every documented NIST "Data type" code (per
// molten-salt-data.pdf) to the msr:EquationForm local name. This is the full
// 12-entry set; a code outside it is a fatal, fail-loud error rather than a
// silent skip.
var equationForms = map[string]string{
	"P1": "Linear",
	"P2": "Polynomial2",
	"P3": "Polynomial3",
	"P4": "Polynomial4",
	"+E": "Arrhenius",
	"E1": "ExtendedArrhenius1",
	"E2": "ExtendedArrhenius2",
	"DP": "DiscretePoint",
	"I1": "Isotherm1",
	"I2": "Isotherm2",
	"I3": "Isotherm3",
	"I4": "Isotherm4",
}

// MapEquationForm maps a NIST "Data type" code to the msr:EquationForm local
// name. A code outside the full documented set returns an error naming it.
func MapEquationForm(code string) (string, error) {
	form, ok := equationForms[code]
	if !ok {
		return "", fmt.Errorf("nist: unknown equation-form code %q", code)
	}
	return form, nil
}

// isIsothermCode reports whether code is one of the composition-isotherm
// codes (I1-I4), which drives the D4 positional-vs-range dispatch and the
// DP/isotherm temperature-column special-casing.
func isIsothermCode(code string) bool {
	switch code {
	case "I1", "I2", "I3", "I4":
		return true
	default:
		return false
	}
}
