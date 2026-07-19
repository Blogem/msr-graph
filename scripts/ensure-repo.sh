#!/usr/bin/env bash
#
# ensure-repo.sh — idempotent check-then-create of the GraphDB repository
# "msr" via GraphDB's REST API, using the vendored repo-config TTL
# (deploy/graphdb/msr-repo-config.ttl). Runs from the HOST against the
# published GraphDB port (see docker-compose.yml, service "graphdb").
#
# Usage: scripts/ensure-repo.sh
# Env:   GRAPHDB_URL (default http://localhost:7200)
#
# Called by `make up` after GraphDB reports healthy.

set -euo pipefail

GRAPHDB_URL="${GRAPHDB_URL:-http://localhost:7200}"
REPO_ID="msr"

# Resolve the repo-config TTL relative to this script's location so the
# script works regardless of the caller's working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_CONFIG="${SCRIPT_DIR}/../deploy/graphdb/msr-repo-config.ttl"

if [[ ! -f "${REPO_CONFIG}" ]]; then
  echo "ensure-repo: repo config not found at ${REPO_CONFIG}" >&2
  exit 1
fi

echo "ensure-repo: checking for repository '${REPO_ID}' at ${GRAPHDB_URL}..."

# CHECK existence: GET /rest/repositories lists all repositories as a JSON
# array of objects; grep for the id field rather than parsing JSON (no jq
# dependency assumed on the host). The pattern tolerates optional whitespace
# around the JSON colon so a change in GraphDB's serialization (compact vs.
# spaced) can't make the check silently miss and attempt a duplicate create.
existing_repos="$(curl -fsS "${GRAPHDB_URL}/rest/repositories")"

if grep -Eq "\"id\"[[:space:]]*:[[:space:]]*\"${REPO_ID}\"" <<<"${existing_repos}"; then
  echo "ensure-repo: repository '${REPO_ID}' already exists — no-op."
  exit 0
fi

echo "ensure-repo: repository '${REPO_ID}' not found — creating from ${REPO_CONFIG}..."

# CREATE: POST /rest/repositories, multipart/form-data field "config".
response_file="$(mktemp)"
trap 'rm -f "${response_file}"' EXIT

http_status="$(
  curl -sS -o "${response_file}" -w '%{http_code}' \
    -X POST "${GRAPHDB_URL}/rest/repositories" \
    -F "config=@${REPO_CONFIG};type=text/turtle"
)"

response_body="$(cat "${response_file}" 2>/dev/null || true)"

if [[ "${http_status}" != "200" && "${http_status}" != "201" ]]; then
  echo "ensure-repo: failed to create repository '${REPO_ID}' (HTTP ${http_status})" >&2
  echo "ensure-repo: response body: ${response_body}" >&2
  exit 1
fi

echo "ensure-repo: repository '${REPO_ID}' created successfully."
