// Package nist is the pure transformation core for the NIST SRD 27 molten
// salt property ingest: parsing the vendored CSV files, filtering to the
// fluoride subset in scope, canonicalizing salt formula + composition,
// minting deterministic IRIs that match the hand-curated seed A-Box, mapping
// NIST equation-form codes to msr:EquationForm individuals, and resolving +
// validating QUDT unit IRIs against a vendored allowlist.
//
// This package performs no I/O against GraphDB or SQLite; it only reads the
// vendored CSV files and the QUDT unit allowlist from disk and returns typed
// Go values. Writing those values to the stores is the later-wave loader's
// job (cmd/loader, internal/store, internal/graph).
package nist

// Property name constants. These are the canonical property identifiers used
// throughout the pipeline (SQLite `property` column, msr:forProperty, and
// the FileCounts/Summary keys returned by Process).
const (
	PropDensity                = "density"
	PropViscosity              = "viscosity"
	PropSurfaceTension         = "surfaceTension"
	PropElectricalConductivity = "electricalConductivity"
)
