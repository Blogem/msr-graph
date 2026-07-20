# salt-canonicalization (delta)

## MODIFIED Requirements

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
