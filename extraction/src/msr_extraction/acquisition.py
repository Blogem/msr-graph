"""Corpus acquisition.

Fetches the openmsr/msr-archive corpus (design.md D1): an LFS-skip, shallow
clone that leaves PDFs as LFS pointers while pulling all OCR ``.txt``
sidecars and the manifest ``README.md``.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable

from msr_extraction.config import Config

logger = logging.getLogger(__name__)


def acquire(config: Config, runner: Callable[..., object] = subprocess.run) -> None:
    """Clone the msr-archive corpus into ``config.archive_dir``.

    Runs, in effect,
    ``GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 <config.msr_archive_url> <config.archive_dir>``.
    Idempotent: if ``config.archive_dir / ".git"`` already exists, the clone
    is skipped (a POC does not chase upstream updates). PDFs stay as LFS
    pointers (``GIT_LFS_SKIP_SMUDGE=1`` prevents git-lfs from fetching the
    binary content they point at); OCR sidecars are ordinary tracked text
    files, so they come in as full content on the same clone.

    ``runner`` is injectable (defaults to :func:`subprocess.run`) so tests can
    supply a fake and assert the constructed command/environment without
    touching the network.
    """
    if (config.archive_dir / ".git").exists():
        logger.info("acquire: checkout already present, skipping clone")
        return

    config.archive_dir.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["GIT_LFS_SKIP_SMUDGE"] = "1"

    cmd = [
        "git",
        "clone",
        "--depth",
        "1",
        config.msr_archive_url,
        str(config.archive_dir),
    ]
    runner(cmd, env=env, check=True)
