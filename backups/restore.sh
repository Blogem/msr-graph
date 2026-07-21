#!/usr/bin/env bash
# Restore an MSR baseline snapshot taken by backup.sh — WITHOUT re-running any
# LLM inference (no load-seed / load-nist / ingest / link / extract needed).
# Replaces the GraphDB repo volume + the SQLite store from the snapshot.
#
# Usage:  bash backups/restore.sh backups/<timestamp>
set -euo pipefail

REPO="${MSR_REPO_DIR:-/Users/jochem/code/msr-graph}"
PROJECT="${MSR_COMPOSE_PROJECT:-msr-graph}"
VOLUME="${MSR_GRAPHDB_VOLUME:-msr-graph_graphdb-data}"
SRC="${1:?usage: restore.sh <backup-dir>}"
# Resolve SRC to an absolute path. Docker only bind-mounts when the -v source is
# absolute (or ./-prefixed); a bare relative name is treated as a *named volume*,
# which silently mounts an empty volume instead of the backup dir.
[ -d "$SRC" ] || { echo "ERROR: backup dir not found: $SRC"; exit 1; }
SRC="$(cd "$SRC" && pwd)"
COMPOSE=(docker compose -p "$PROJECT" -f "$REPO/docker-compose.yml")

[ -f "$SRC/graphdb-home.tgz" ] || { echo "ERROR: $SRC/graphdb-home.tgz not found"; exit 1; }
[ -f "$SRC/msr.db" ]          || { echo "ERROR: $SRC/msr.db not found"; exit 1; }

echo "==> stopping graphdb"
"${COMPOSE[@]}" stop graphdb

echo "==> wiping + restoring GraphDB volume: $VOLUME"
docker run --rm -v "$VOLUME":/data -v "$SRC":/backup alpine sh -c \
  'rm -rf /data/* /data/..?* /data/.[!.]* 2>/dev/null; tar xzf /backup/graphdb-home.tgz -C /data'

echo "==> restoring SQLite measurement store"
cp -f "$SRC/msr.db" "$REPO/data/msr.db"

if [ -f "$SRC/corpus-traces.tgz" ]; then
  echo "==> restoring corpus traces"
  tar xzf "$SRC/corpus-traces.tgz" -C "$REPO/data"
fi

echo "==> starting graphdb"
"${COMPOSE[@]}" start graphdb

echo "==> restore complete."
echo "    The baseline (graphs + measurement rows) is loaded — do NOT run"
echo "    load-seed / load-nist / ingest / link / extract. Verify with:"
echo "      curl -s http://localhost:7200/repositories/msr --data-urlencode \\"
echo "        'query=SELECT (COUNT(*) AS ?n) WHERE { GRAPH <urn:msr:data> { ?s ?p ?o } }' -H 'Accept: text/csv'"
