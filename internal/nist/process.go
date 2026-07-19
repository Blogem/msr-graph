package nist

import (
	"fmt"
	"path/filepath"
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
	return measurements, summary, nil
}
