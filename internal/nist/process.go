package nist

import (
	"fmt"
	"path/filepath"
	"sort"
	"strconv"
)

// FileCounts summarizes one vendored property file's ingest outcome.
type FileCounts struct {
	Read       int
	Kept       int
	OutOfScope int
	Flagged    int
}

// Summary is the run-level report Process returns alongside the kept
// measurements: per-file counts, distinct canonical salts, and the
// equation-form codes seen.
type Summary struct {
	PerFile       map[string]FileCounts // keyed by property name
	DistinctSalts int
	EquationForms map[string]int // eqform local name -> count
}

// Process runs the full pipeline over the four vendored files in dir, validating
// every emitted unit IRI against units (abort on unknown) and failing on a truly
// unknown equation-form code. Out-of-scope (non-fluoride) rows are counted, not
// written; unparseable rows are flagged. Returns kept measurements + a summary.
func Process(dir string, units *UnitAllowlist) ([]Measurement, Summary, error) {
	summary := Summary{
		PerFile:       make(map[string]FileCounts, len(propertyFiles)),
		EquationForms: make(map[string]int),
	}
	var measurements []Measurement
	distinctSalts := make(map[string]struct{})

	for _, pf := range propertyFiles {
		path := filepath.Join(dir, pf.Name)
		rows, err := parseFile(path)
		if err != nil {
			return nil, Summary{}, fmt.Errorf("nist: %s: %w", pf.Name, err)
		}

		var counts FileCounts
		for _, row := range rows {
			counts.Read++

			if !IsFluoride(row.Salt) {
				counts.OutOfScope++
				continue
			}

			form, err := MapEquationForm(row.DataType)
			if err != nil {
				return nil, Summary{}, fmt.Errorf("nist: %s: salt %q: %w", pf.Name, row.Salt, err)
			}

			salt, err := Canonicalize(row.Salt, row.CompositionRange, row.DataType)
			if err != nil {
				// Unparseable (bad formula/composition, or positional sum
				// outside tolerance): flag for manual review, don't write,
				// don't abort the run.
				counts.Flagged++
				continue
			}

			m, err := buildMeasurement(row, salt, form, row.DataType, pf.Property, units)
			if err != nil {
				return nil, Summary{}, fmt.Errorf("nist: %s: salt %q: %w", pf.Name, row.Salt, err)
			}

			counts.Kept++
			measurements = append(measurements, m)
			distinctSalts[salt.Canonical] = struct{}{}
			summary.EquationForms[form]++
		}

		summary.PerFile[pf.Property] = counts
	}

	summary.DistinctSalts = len(distinctSalts)
	disambiguateLocators(measurements)
	return measurements, summary, nil
}

// disambiguateLocators finds groups of measurements that share an identical
// Locator -- the vendored NIST data carries multiple measurements for some
// (property, salt) pairs (e.g. several DiscretePoint rows plus an Arrhenius
// fit for BeF2 electrical conductivity) -- and mints a unique Locator + IRI
// for every member of a colliding group. Singleton groups (the overwhelming
// majority) are left completely unchanged, so the existing seed no-op and
// anchor locators (FLiBe density, FLiNaK density) are preserved exactly.
func disambiguateLocators(measurements []Measurement) {
	groups := make(map[string][]int, len(measurements))
	for i, m := range measurements {
		groups[m.Locator] = append(groups[m.Locator], i)
	}

	for _, idxs := range groups {
		if len(idxs) < 2 {
			continue
		}

		// Sort the group's members by (TMin, EquationForm, original index)
		// for a deterministic disambiguation order.
		sort.Slice(idxs, func(a, b int) bool {
			ma, mb := measurements[idxs[a]], measurements[idxs[b]]
			switch {
			case ma.TMin == nil && mb.TMin != nil:
				return true
			case ma.TMin != nil && mb.TMin == nil:
				return false
			case ma.TMin != nil && mb.TMin != nil && *ma.TMin != *mb.TMin:
				return *ma.TMin < *mb.TMin
			}
			if ma.EquationForm != mb.EquationForm {
				return ma.EquationForm < mb.EquationForm
			}
			return idxs[a] < idxs[b]
		})

		base := measurements[idxs[0]].Locator
		seen := make(map[string]bool, len(idxs))
		for order, i := range idxs {
			locator := base + "@" + tMinSlug(measurements[i].TMin)
			if seen[locator] {
				locator = fmt.Sprintf("%s-%d", locator, order+1)
			}
			seen[locator] = true
			measurements[i].Locator = locator
			measurements[i].IRI = buildMeasurementIRI(locator)
		}
	}
}

// tMinSlug renders a measurement's TMin as the "@<tmin>" discriminator
// suffix appended by disambiguateLocators: the shortest round-tripping
// decimal, or "na" when TMin is absent.
func tMinSlug(v *float64) string {
	if v == nil {
		return "na"
	}
	return strconv.FormatFloat(*v, 'f', -1, 64)
}
