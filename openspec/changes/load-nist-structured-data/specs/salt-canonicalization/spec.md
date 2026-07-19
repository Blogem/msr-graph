# Spec: salt-canonicalization

## ADDED Requirements

### Requirement: Canonical salt form
The system SHALL normalize every salt at the ingest boundary to a canonical form: components sorted by byte-wise ascending order of their formula token, composition mole-% values reordered in lockstep with the components, and each mole-% formatted to exactly one decimal place. The canonical form is used identically in the salt IRI, the locator, the SQLite `salt` column, and the `rdfs:label`.

#### Scenario: FLiBe formula canonicalizes
- **WHEN** the raw salt `LiF-BeF2` with composition `34.0-66.0` is canonicalized
- **THEN** the canonical string is `BeF2-LiF | 66.0-34.0` (components alphabetized, composition reordered in lockstep, one decimal)

#### Scenario: Ternary formula canonicalizes deterministically
- **WHEN** the raw salt `LiF-NaF-KF` is canonicalized
- **THEN** the components sort to `KF-LiF-NaF` with composition reordered in lockstep

#### Scenario: Pure salt canonicalizes
- **WHEN** the raw salt `LiF` with composition `100` is canonicalized
- **THEN** the canonical string is `LiF | 100.0` with a single constituent at mole fraction 1.0

### Requirement: Deterministic IRI minting without blank nodes
The loader SHALL mint salt, constituent, and measurement IRIs deterministically from the canonical form, using no blank nodes, and matching the seed A-Box minting scheme: salt `msrd:salt-{formula}-{composition}`, constituent `{salt-iri}-c-{compound}`, measurement `msrd:m-{locator-slug}` (locator with `/ # |` replaced by `-`).

#### Scenario: Salt IRI matches the seed
- **WHEN** the loader mints the IRI for the FLiBe coolant salt (canonical `BeF2-LiF | 66.0-34.0`)
- **THEN** the IRI is `msrd:salt-BeF2-LiF-66.0-34.0`, identical to the seed A-Box individual

#### Scenario: Measurement IRI is a slugged locator
- **WHEN** the loader mints the IRI for the FLiBe density measurement with locator `nist-srd27/density#BeF2-LiF|66.0-34.0`
- **THEN** the IRI is `msrd:m-nist-srd27-density-BeF2-LiF-66.0-34.0`

### Requirement: Positional-vs-range composition disambiguation
The loader SHALL disambiguate the `Composition range` column: when the value count equals the component count and the values sum to approximately 100 (within a fixed tolerance), the values are positional single-composition mole fractions; when they instead encode a per-component min–max range, the loader emits `moleFractionMin`/`moleFractionMax`; when neither interpretation holds, the row SHALL be flagged for manual review and skipped rather than silently dropped.

#### Scenario: Positional composition
- **WHEN** a two-component salt has two composition values summing to ≈100
- **THEN** each value becomes that constituent's `moleFraction`

#### Scenario: Ambiguous composition flagged
- **WHEN** a composition can be read neither as a positional set summing to ≈100 nor as a per-component range
- **THEN** the row is flagged for manual review, reported in the run summary, and not written to either store

### Requirement: Shared canonicalization fixture
This change SHALL author `testdata/salt-canonicalization.json` as a set of raw→canonical cases (canonical string plus per-component ordered mole-%). The Go canonicalizer MUST pass every case, and the fixture is the drift guard that chunk 6's Python normalizer must also pass so the two implementations cannot diverge.

#### Scenario: Go canonicalizer passes the fixture
- **WHEN** the Go tests run against `testdata/salt-canonicalization.json`
- **THEN** every raw input produces the fixture's expected canonical string and ordered mole-%

#### Scenario: Fixture covers the anchor cases
- **WHEN** the fixture is authored
- **THEN** it includes at least the `LiF-BeF2,34.0-66.0` → `BeF2-LiF | 66.0-34.0` case and a ternary reordering case
