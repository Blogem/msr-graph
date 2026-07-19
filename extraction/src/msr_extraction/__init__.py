"""MSR extraction pipeline.

Acquires the openmsr/msr-archive corpus, parses its manifest, normalizes
and segments the curated document set, and writes Document provenance
nodes into the graph. See ``openspec/changes/ingest-archive-documents``
for the design (chunk 5) that grew this package from the chunk-1 scaffold.
"""

from msr_extraction.cli import main

__all__ = ["main"]
