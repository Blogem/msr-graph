# salt-canonicalization Specification

## Purpose

Define the salt canonicalization contract used at the ingest boundary: a single canonical salt form, deterministic IRI minting without blank nodes, positional-vs-range composition disambiguation driven by the equation-form code, and a shared canonicalization fixture that guards the Go and Python implementations against drift.

## Requirements

### Requirement: Canonical salt form
The system SHALL normalize every salt at the ingest boundary to a canonical form: components sorted by byte-wise ascending order of their formula token, composition mole-% values reordered in lockstep with the components, and each mole-% formatted to exactly one decimal place. The canonical form is used identically in the salt IRI, the locator, the SQLite `salt` column, and the `rdfs:label`.

#### Scenario: Unsorted formula reorders components and composition in lockstep
- **WHEN** a hypothetical unsorted raw salt `LiF-BeF2` with composition `34.0-66.0` is canonicalized
- **THEN** the canonical string is `BeF2-LiF | 66.0-34.0` (components alphabetized, composition reordered in lockstep, one decimal) — this demonstrates the lockstep-reorder rule, not the real NIST FLiBe row (see below)

#### Scenario: Real NIST FLiBe row canonicalizes unchanged
- **WHEN** the real NIST FLiBe row, raw salt `BeF2-LiF` with composition `34.0-66.0` (already byte-sorted), is canonicalized
- **THEN** the canonical string is `BeF2-LiF | 34.0-66.0`, unchanged from the raw order, and the salt IRI is `msrd:salt-BeF2-LiF-34.0-66.0`

#### Scenario: Ternary formula canonicalizes deterministically
- **WHEN** the raw salt `LiF-NaF-KF` is canonicalized
- **THEN** the components sort to `KF-LiF-NaF` with composition reordered in lockstep

#### Scenario: Pure salt canonicalizes
- **WHEN** the raw salt `LiF` with composition `100` is canonicalized
- **THEN** the canonical string is `LiF | 100.0` with a single constituent at mole fraction 1.0

### Requirement: Deterministic IRI minting without blank nodes
The loader SHALL mint salt, constituent, and measurement IRIs deterministically from the canonical form, using no blank nodes, per the deterministic minting scheme: salt `msrd:salt-{formula}-{composition}`, constituent `{salt-iri}-c-{compound}`, measurement `msrd:m-{locator-slug}` (locator with `/ # |` replaced by `-`).

#### Scenario: Salt IRI is deterministic from the canonical form
- **WHEN** the loader mints the IRI for the FLiBe coolant salt (canonical `BeF2-LiF | 34.0-66.0`)
- **THEN** the IRI is `msrd:salt-BeF2-LiF-34.0-66.0`

#### Scenario: Measurement IRI is a slugged locator
- **WHEN** the loader mints the IRI for the FLiBe density measurement with locator `nist-srd27/density#BeF2-LiF|34.0-66.0`
- **THEN** the IRI is `msrd:m-nist-srd27-density-BeF2-LiF-34.0-66.0`

#### Scenario: Range-composition (isotherm) salt canonicalizes and mints
- **WHEN** the raw isotherm row `KF-ZrF4, 0.0-33.3 ZrF4` is canonicalized
- **THEN** the canonical string is `KF-ZrF4 | ZrF4 0.0-33.3`, the salt IRI is `msrd:salt-KF-ZrF4-ZrF4-0.0-33.3`, and the constituents carry `moleFractionMin`/`moleFractionMax` (`ZrF4`: `0.0`/`0.333`; `KF`: `0.667`/`1.0`) instead of a single `moleFraction`

### Requirement: Positional-vs-range composition disambiguation driven by the equation-form code
The loader SHALL determine how to interpret the `Composition range` column from the row's `Data type` equation-form code, not from the shape of the values: isotherm codes (`I1`–`I4`) always encode a per-component composition range (`X-Y COMPONENT`), emitted as `moleFractionMin`/`moleFractionMax`; every other documented code (`P1`–`P4`, `+E`, `E1`, `E2`, `DP`) always encodes a positional single composition, with values expected to sum to approximately 100 within a **±2.0 mol% tolerance**. A positional row whose values fail that tolerance SHALL be flagged for manual review and skipped rather than silently dropped.

#### Scenario: Positional composition
- **WHEN** a non-isotherm row has composition values summing to ≈100 within ±2.0 mol% (e.g. `26.04-72.96`, summing to 99.0)
- **THEN** each value becomes that constituent's `moleFraction`

#### Scenario: Isotherm composition is always a range
- **WHEN** a row carries an isotherm `Data type` code (`I1`–`I4`)
- **THEN** its `Composition range` column is parsed as a per-component min–max range regardless of whether the values would also sum to ≈100

#### Scenario: Out-of-tolerance positional composition flagged
- **WHEN** a non-isotherm row's composition values sum to more than ±2.0 mol% away from 100
- **THEN** the row is flagged for manual review, reported in the run summary, and not written to either store

### Requirement: Shared canonicalization fixture
This change SHALL author `testdata/salt-canonicalization.json` as a set of raw→canonical cases (canonical string plus per-component ordered mole-%). The Go canonicalizer MUST pass every case, and the fixture is the drift guard that chunk 6's Python normalizer must also pass so the two implementations cannot diverge.

#### Scenario: Go canonicalizer passes the fixture
- **WHEN** the Go tests run against `testdata/salt-canonicalization.json`
- **THEN** every raw input produces the fixture's expected canonical string and ordered mole-%

#### Scenario: Fixture covers the anchor cases
- **WHEN** the fixture is authored
- **THEN** it includes at least: the real NIST FLiBe row `BeF2-LiF,34.0-66.0` → `BeF2-LiF | 34.0-66.0` (already sorted, unchanged), the hypothetical unsorted reorder case `LiF-BeF2,34.0-66.0` → `BeF2-LiF | 66.0-34.0`, and a ternary reordering case (`LiF-NaF-KF` → `KF-LiF-NaF`)
