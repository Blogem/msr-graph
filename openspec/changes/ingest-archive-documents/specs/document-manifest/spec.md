## ADDED Requirements

### Requirement: Manifest parsed into structured records
The system SHALL parse the msr-archive `README.md` markdown table into structured document records, each carrying the title, report number, date, and OCR sidecar path. Parsing MUST be pure and offline (operating on the already-checked-out `README.md`, no network). Rows that do not match the expected table shape (header, separator, or malformed rows) MUST be skipped without aborting the parse.

#### Scenario: Real manifest rows produce structured records
- **WHEN** the parser runs over the msr-archive `README.md`
- **THEN** each conforming table row yields a record with its title, report number, date, and OCR sidecar path

#### Scenario: Header and separator rows are ignored
- **WHEN** the parser encounters the table's header row, its `---` separator row, or a malformed row
- **THEN** those rows are skipped and do not appear as document records

### Requirement: Manifest is the source of curated document metadata
The parsed manifest SHALL be the single source of each curated document's OCR sidecar path and of the metadata (title, date) used when writing its `Document` node. A curated report number MUST resolve through the manifest to its OCR sidecar path.

#### Scenario: Curated report resolves to its OCR sidecar
- **WHEN** a curated report number is looked up against the parsed manifest
- **THEN** the manifest yields that document's OCR sidecar path and its title/date metadata
