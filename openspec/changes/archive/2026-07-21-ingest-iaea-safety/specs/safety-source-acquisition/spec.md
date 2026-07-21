## ADDED Requirements

### Requirement: Safety sources acquired into a gitignored cache under a tracked manifest
The system SHALL acquire the safety-genre sources — IAEA SRS-123 (PUB2027), the GIF (Holcomb) MSR safety analysis, ORNL/TM-2006/12, and the ORNL MSR technical-&-safety considerations report — into the gitignored cache `data/safety/` via the tracked `scripts/fetch-safety-sources.sh`. Acquisition MUST be idempotent (present files are not re-downloaded). Neither the source PDFs nor their full extracted text SHALL be committed to the repository; the only tracked artifacts are the fetch script and a committed attributed manifest.

#### Scenario: Fetch populates the cache idempotently
- **WHEN** the fetch step runs against a `data/safety/` already containing the sources
- **THEN** it leaves the existing files unchanged and does not error, and no PDF or full-text file is added to Git tracking

#### Scenario: Manifest records attribution and section scope
- **WHEN** the manifest is read
- **THEN** each source has an identifier, title, publisher, rights statement, source URL, date, and the ingested section/page scope (SRS-123 scoped to §2.1.2.5 / §3.2 / §5.1.8; the GIF and ORNL sources whole)

### Requirement: PDF text extraction scoped to MSR-relevant sections
The system SHALL extract text from each cached PDF into `data/safety/{id}.txt` using a text-layer extractor (pypdf), restricted to the section/page scope declared in the manifest, and SHALL then produce `data/safety/{id}/normalized.txt` + `segments.jsonl` by reusing the existing corpus normalization and segmentation pipeline (no forked normalizer).

#### Scenario: Only scoped sections are extracted
- **WHEN** extraction runs for a source with a declared section scope
- **THEN** the produced `{id}.txt` contains the scoped sections and excludes out-of-scope pages

#### Scenario: Normalized artifacts match the pipeline input format
- **WHEN** normalization and segmentation complete for a safety source
- **THEN** `data/safety/{id}/normalized.txt` and `segments.jsonl` exist with the same schema the NER stages consume (sentence text + absolute char offsets into `normalized.txt`)

### Requirement: Attributed Document provenance nodes
The system SHALL write one `msr:Document` per safety source into `urn:msr:data`, keyed by a stable identifier, carrying `rdfs:label` (title), `dcterms:identifier`, `dcterms:date`, `dcterms:publisher`, `dcterms:rights`, and `dcterms:source` (URL), with the established provenance edges (`prov:wasDerivedFrom`/`prov:wasGeneratedBy`, per-run activity in `urn:msr:provenance`). IRIs SHALL be deterministic and writes additive, so re-runs are set-semantics no-ops in `urn:msr:data`.

#### Scenario: Document node carries mandatory attribution
- **WHEN** the safety `Document` nodes are written
- **THEN** each carries a non-empty `dcterms:publisher` and `dcterms:rights` and a resolvable `dcterms:source` URL, in addition to the standard document metadata and provenance edges

#### Scenario: Re-running acquisition is idempotent in the data graph
- **WHEN** the safety ingest runs a second time
- **THEN** the `urn:msr:data` triple count is unchanged (deterministic IRIs, additive `INSERT DATA`), while `urn:msr:provenance` gains a new per-run activity
