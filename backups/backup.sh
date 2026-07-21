#!/usr/bin/env bash
# Snapshot the MSR baseline so it can be reloaded WITHOUT re-running the
# expensive link/extract LLM inference. Captures:
#   1. the GraphDB repo storage volume (all named graphs + SHACL shapes + config)
#   2. the SQLite measurement store (data/msr.db)
#   3. the corpus LLM-trace artifacts (mentions.jsonl from link, relations.jsonl
#      from extract, + segments/normalized) — excludes the re-cloneable raw archive
#
# For a CONSISTENT snapshot this briefly stops the graphdb container, so do NOT
# run it while `make link` / `make extract` is still writing.
#
# Usage:  bash backups/backup.sh            # -> backups/<timestamp>/
#         bash backups/backup.sh /path/dir  # -> custom dir
set -euo pipefail

REPO="${MSR_REPO_DIR:-/Users/jochem/code/msr-graph}"
PROJECT="${MSR_COMPOSE_PROJECT:-msr-graph}"
VOLUME="${MSR_GRAPHDB_VOLUME:-msr-graph_graphdb-data}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${1:-$REPO/backups/$STAMP}"
COMPOSE=(docker compose -p "$PROJECT" -f "$REPO/docker-compose.yml")

mkdir -p "$DEST"
echo "==> backing up MSR baseline to $DEST"

echo "==> stopping graphdb for a consistent volume snapshot (brief downtime)"
"${COMPOSE[@]}" stop graphdb

echo "==> snapshotting GraphDB volume: $VOLUME"
docker run --rm -v "$VOLUME":/data:ro -v "$DEST":/backup alpine \
  tar czf /backup/graphdb-home.tgz -C /data .

echo "==> restarting graphdb"
"${COMPOSE[@]}" start graphdb

echo "==> copying SQLite measurement store"
cp -f "$REPO/data/msr.db" "$DEST/msr.db"

if [ -d "$REPO/data/corpus" ]; then
  echo "==> archiving corpus traces (excluding raw msr-archive)"
  tar czf "$DEST/corpus-traces.tgz" -C "$REPO/data" --exclude='corpus/msr-archive' corpus
fi

echo "==> writing MANIFEST"
{
  echo "created:  $STAMP"
  echo "git HEAD: $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null) ($(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null))"
  echo "volume:   $VOLUME"
  echo "--- graph statement counts (best effort; graphdb may still be warming up) ---"
  for i in 1 2 3 4 5; do
    out=$(curl -s "http://localhost:7200/repositories/msr" \
      --data-urlencode 'query=SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g ORDER BY ?g' \
      -H "Accept: text/csv" 2>/dev/null) && [ -n "$out" ] && { echo "$out"; break; } || sleep 3
  done
  echo "--- sqlite rows by source ---"
  python3 -c "import sqlite3;c=sqlite3.connect('$DEST/msr.db');print(dict(c.execute('SELECT source,COUNT(*) FROM measurement_value GROUP BY source').fetchall()))" 2>/dev/null || true
} > "$DEST/MANIFEST.txt"
cat "$DEST/MANIFEST.txt"

echo "==> backup complete:"
ls -lh "$DEST"
