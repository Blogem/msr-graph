"""Corpus acquisition.

Fetches the openmsr/msr-archive corpus (design.md D1): an LFS-skip, shallow
clone that leaves PDFs as LFS pointers while pulling all OCR ``.txt``
sidecars and the manifest ``README.md``.
"""

from __future__ import annotations

from msr_extraction.config import Config


def acquire(config: Config) -> None:
    """Clone the msr-archive corpus into ``config.archive_dir``.

    Runs, in effect,
    ``GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 <config.msr_archive_url> <config.archive_dir>``.
    Idempotent: if ``config.archive_dir / ".git"`` already exists, the clone
    is skipped (a POC does not chase upstream updates). PDFs stay as LFS
    pointers; OCR sidecars are pulled in full.
    """
    raise NotImplementedError("task 2.1")
