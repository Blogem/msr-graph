#!/usr/bin/env bash
# Fetch the IAEA / GIF / ORNL safety sources for the `ingest-iaea-safety` (chunk 11)
# requirement layer into the gitignored cache `data/safety/`.
#
# These PDFs are © their publishers (IAEA "all rights reserved"; ORNL/GIF public).
# They are cached locally for the build but NOT committed — only this script and the
# citation manifest (docs/SAFETY_THREAD_SPIKE.md) live in git. This mirrors how the
# msr-archive OCR corpus is handled (gitignored cache, cited in docs).
set -euo pipefail

DEST="$(cd "$(dirname "$0")/.." && pwd)/data/safety"
mkdir -p "$DEST"
UA="Mozilla/5.0"

fetch() { # url  filename
  if [ -s "$DEST/$2" ]; then
    echo ">> $2 — skip (present)"
    return 0
  fi
  echo ">> $2"
  curl -fsSL -A "$UA" -o "$DEST/$2" "$1"
}

# IAEA anchor — Safety Reports Series No. 123 (PUB2027): §2.1.2.5 MSRs + the three
# fundamental safety functions (confinement, reactivity control, heat removal).
fetch "https://www-pub.iaea.org/MTCD/Publications/PDF/PUB2027_Web.pdf" \
      "PUB2027_SRS-123.pdf"

# GIF MSR requirement/function layer — Holcomb, "MSR Safety Analysis" (a GIF-MSR
# dedicated SDC/SDG report is not yet public; this is the public GIF MSR source that
# ties fundamental safety functions to salt thermophysical properties).
fetch "https://www.gen-4.org/sites/default/files/2024-09/Dr.%20Dave%20Holcomb%2026%20AUG%202020_GIF.pdf" \
      "GIF_Holcomb_MSR-safety-analysis.pdf"

# ORNL coolant-selection assessment — ORNL/TM-2006/12, coolant selection organised by
# the exact properties we hold (melting point, vapor pressure, viscosity, thermal
# conductivity, heat capacity), with LiF-BeF2 values.
fetch "https://info.ornl.gov/sites/publications/Files/Pub57476.pdf" \
      "ORNL-TM-2006-12_coolant-assessment.pdf"

# ORNL MSR technical & safety considerations (secondary requirement-layer context).
fetch "https://info.ornl.gov/sites/publications/Files/Pub181692.pdf" \
      "ORNL_MSR-technical-safety-considerations.pdf"

echo "Done. Cached in $DEST (gitignored)."
