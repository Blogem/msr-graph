"""Shared pytest configuration for the extraction test suite.

Tests are expected to run against an editable install
(``pip install -e "extraction[test]"``) so ``import msr_extraction``
resolves normally. This module adds ``extraction/src`` onto ``sys.path`` as
a fallback so the suite still collects and runs when invoked without the
editable install (e.g. plain ``pytest extraction/tests``).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
