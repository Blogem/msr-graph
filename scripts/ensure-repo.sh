#!/usr/bin/env bash
#
# ensure-repo.sh — idempotent check-then-create of a GraphDB repository via
# GraphDB's REST API, using the vendored repo-config TTL
# (deploy/graphdb/msr-repo-config.ttl). Runs from the HOST against the
# published GraphDB port (see docker-compose.yml, service "graphdb").
#
# Also (shacl-validation chunk 13):
#   - detects a pre-SHACL existing repo and fails with upgrade guidance
#     (design D7), so bring-up on an old graphdb-data volume can't silently
#     no-op into a repo that looks SHACL-enabled but isn't;
#   - regenerates the unit-allowlist shape fragment from
#     ontology/qudt-units.json (design D3) so a stale hand-edit can't drift
#     from the loader's allowlist;
#   - loads the shape catalogue into the reserved shapes graph
#     (http://rdf4j.org/schema/rdf4j#SHACLShapeGraph) so a fresh stack
#     enforces shapes with no manual step (design D2, D4.1/4.2).
#
# Also (isolate-integration-test-repo, design D4):
#   - REPO_ID selects which repository to ensure (default "msr", so `make
#     up`'s existing call is unchanged). For any REPO_ID other than "msr",
#     the vendored config is copied to a tempfile with `rep:repositoryID
#     "msr"` swapped to the chosen id (SHACL is fixed at repo-creation time,
#     so the id must be baked into the POSTed config), and the tempfile is
#     cleaned up on exit;
#   - REPO_RESET=1 drops the repository first (DELETE
#     /rest/repositories/{REPO_ID}, tolerating 200/204/404) so each
#     `make test-repo` run starts from a clean repo. Guarded so it can NEVER
#     drop "msr": REPO_ID=msr together with REPO_RESET=1 fails loudly.
#
# Usage: scripts/ensure-repo.sh
# Env:   GRAPHDB_URL (default http://localhost:7200)
#        REPO_ID      (default msr)
#        REPO_RESET   (default unset/0; "1" drops REPO_ID before creating —
#                      refused when REPO_ID=msr)
#
# Called by `make up` (REPO_ID=msr, the default) after GraphDB reports
# healthy, and by `make test-repo` (REPO_ID=msr-test REPO_RESET=1) to
# provision the disposable integration-test repository.

set -euo pipefail

GRAPHDB_URL="${GRAPHDB_URL:-http://localhost:7200}"
REPO_ID="${REPO_ID:-msr}"
REPO_RESET="${REPO_RESET:-0}"
SHACL_SHAPES_GRAPH="http://rdf4j.org/schema/rdf4j#SHACLShapeGraph"
# URL-encoded form of the reserved shapes-graph IRI above, for the Graph
# Store Protocol endpoint's `?graph=` query parameter.
SHACL_SHAPES_GRAPH_ENC="http%3A%2F%2Frdf4j.org%2Fschema%2Frdf4j%23SHACLShapeGraph"

# Resolve paths relative to this script's location so the script works
# regardless of the caller's working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_CONFIG="${REPO_ROOT}/deploy/graphdb/msr-repo-config.ttl"
SHAPES_FILE="${REPO_ROOT}/deploy/graphdb/msr-shapes.ttl"
SHAPES_UNITS_FILE="${REPO_ROOT}/deploy/graphdb/msr-shapes-units.ttl"

if [[ ! -f "${REPO_CONFIG}" ]]; then
  echo "ensure-repo: repo config not found at ${REPO_CONFIG}" >&2
  exit 1
fi

# Single cleanup trap for every tempfile this script creates (the
# non-"msr" config copy below, and the create-response body further down),
# so multiple `trap ... EXIT` calls can't clobber each other.
TMP_FILES=()
cleanup_tmp_files() {
  local f
  # Guard the expansion with a length check rather than relying on
  # "${arr[@]:-}" alone: bash 3.2 (still the default /usr/bin/env bash on
  # macOS) treats "${arr[@]}" on an empty array as an unbound-variable
  # error under `set -u` regardless of the ":-" fallback.
  if [[ "${#TMP_FILES[@]}" -gt 0 ]]; then
    for f in "${TMP_FILES[@]}"; do
      rm -f "${f}"
    done
  fi
}
trap cleanup_tmp_files EXIT

# REPO_RESET guard (D4): never allow a reset to touch the real "msr" repo.
if [[ "${REPO_RESET}" == "1" ]]; then
  if [[ "${REPO_ID}" == "msr" ]]; then
    echo "ensure-repo: ERROR — REPO_RESET=1 with REPO_ID=msr is refused." >&2
    echo "ensure-repo: resetting/dropping the production 'msr' repository is" >&2
    echo "ensure-repo: never allowed via this flag. Use a non-'msr' REPO_ID" >&2
    echo "ensure-repo: (e.g. REPO_ID=msr-test, as 'make test-repo' does)." >&2
    exit 1
  fi

  echo "ensure-repo: REPO_RESET=1 — dropping repository '${REPO_ID}' if it exists..."
  reset_status="$(
    curl -sS -o /dev/null -w '%{http_code}' \
      -X DELETE "${GRAPHDB_URL}/rest/repositories/${REPO_ID}"
  )"
  case "${reset_status}" in
    200|204|404) : ;;
    *)
      echo "ensure-repo: failed to drop repository '${REPO_ID}' before reset (HTTP ${reset_status})" >&2
      exit 1
      ;;
  esac
  echo "ensure-repo: repository '${REPO_ID}' dropped (or did not already exist)."
fi

# Resolve the config to POST on create. SHACL is fixed at repo-creation
# time, so for any REPO_ID other than "msr" the vendored config's
# `rep:repositoryID "msr"` must be swapped to the chosen id before it is
# POSTed — done via a tempfile copy so deploy/graphdb/msr-repo-config.ttl
# itself is never touched.
if [[ "${REPO_ID}" == "msr" ]]; then
  REPO_CONFIG_ACTIVE="${REPO_CONFIG}"
else
  REPO_CONFIG_ACTIVE="$(mktemp)"
  TMP_FILES+=("${REPO_CONFIG_ACTIVE}")
  sed "s/rep:repositoryID \"msr\"/rep:repositoryID \"${REPO_ID}\"/" \
    "${REPO_CONFIG}" > "${REPO_CONFIG_ACTIVE}"
fi

# ---------------------------------------------------------------------------
# Helper: does a downloaded repository config indicate SHACL is enabled?
# GraphDB's config-download endpoint re-serializes the sail-type value as
# "rdf4j:ShaclSail" (confirmed live against GraphDB 11.4.2 — see
# msr-repo-config.ttl's header comment and task 1.2); grep for the
# vocabulary-independent substring "ShaclSail" so this keeps working even if
# GraphDB changes the prefix it emits.
config_is_shacl_enabled() {
  local config_body="$1"
  grep -q "ShaclSail" <<<"${config_body}"
}
# ---------------------------------------------------------------------------

echo "ensure-repo: checking for repository '${REPO_ID}' at ${GRAPHDB_URL}..."

# CHECK existence: GET /rest/repositories lists all repositories as a JSON
# array of objects; grep for the id field rather than parsing JSON (no jq
# dependency assumed on the host). The pattern tolerates optional whitespace
# around the JSON colon so a change in GraphDB's serialization (compact vs.
# spaced) can't make the check silently miss and attempt a duplicate create.
existing_repos="$(curl -fsS "${GRAPHDB_URL}/rest/repositories")"

if grep -Eq "\"id\"[[:space:]]*:[[:space:]]*\"${REPO_ID}\"" <<<"${existing_repos}"; then
  echo "ensure-repo: repository '${REPO_ID}' already exists — checking it is SHACL-enabled (D7)..."

  # D7: an existing repo predating this change would otherwise be silently
  # left untouched by check-then-create, so SHACL would appear "on" (this
  # script ran) but never actually validate anything. Fail loudly instead.
  existing_config="$(curl -fsS -H "Accept: text/turtle" "${GRAPHDB_URL}/repositories/${REPO_ID}/config")"

  if ! config_is_shacl_enabled "${existing_config}"; then
    echo "ensure-repo: ERROR — repository '${REPO_ID}' exists but predates SHACL." >&2
    echo "ensure-repo: its config has no ShaclSail wrapper / sail-shacl:* params," >&2
    echo "ensure-repo: so writes are NOT being validated even though this script ran." >&2
    echo "ensure-repo: SHACL is fixed at repository-creation time and cannot be" >&2
    echo "ensure-repo: enabled on an existing repository (see design.md D1/D7)." >&2
    echo "ensure-repo: to fix, drop the graphdb-data volume and recreate:" >&2
    echo "ensure-repo:   docker compose down -v && make up" >&2
    exit 1
  fi

  echo "ensure-repo: repository '${REPO_ID}' is SHACL-enabled — no-op on create."
else
  echo "ensure-repo: repository '${REPO_ID}' not found — creating from ${REPO_CONFIG_ACTIVE}..."

  # CREATE: POST /rest/repositories, multipart/form-data field "config".
  response_file="$(mktemp)"
  TMP_FILES+=("${response_file}")

  http_status="$(
    curl -sS -o "${response_file}" -w '%{http_code}' \
      -X POST "${GRAPHDB_URL}/rest/repositories" \
      -F "config=@${REPO_CONFIG_ACTIVE};type=text/turtle"
  )"

  response_body="$(cat "${response_file}" 2>/dev/null || true)"

  if [[ "${http_status}" != "200" && "${http_status}" != "201" ]]; then
    echo "ensure-repo: failed to create repository '${REPO_ID}' (HTTP ${http_status})" >&2
    echo "ensure-repo: response body: ${response_body}" >&2
    exit 1
  fi

  echo "ensure-repo: repository '${REPO_ID}' created successfully (SHACL-enabled)."
fi

# ---------------------------------------------------------------------------
# Shapes-load (design D2, D3, D4; tasks 3.2, 4.1, 4.2)
#
# Regenerate the unit-allowlist shape fragment first (3.2), so a stale
# hand-edit of msr-shapes-units.ttl can never drift from
# ontology/qudt-units.json — the same allowlist the Go loader consumes.
# cmd/gen-unit-shape is provided by another chunk-13 task; this step assumes
# a `go` toolchain is available in the bootstrap context (the same
# assumption `make test`/`make chat` already make by invoking `go` directly
# from the host).
echo "ensure-repo: regenerating unit-allowlist shape fragment (ontology/qudt-units.json -> ${SHAPES_UNITS_FILE})..."

if ! command -v go >/dev/null 2>&1; then
  echo "ensure-repo: ERROR — 'go' not found on PATH; cannot regenerate ${SHAPES_UNITS_FILE}." >&2
  echo "ensure-repo: install a Go toolchain (see go.mod) or run 'go run ./cmd/gen-unit-shape'" >&2
  echo "ensure-repo: manually from the repo root before re-running 'make up'." >&2
  exit 1
fi

(cd "${REPO_ROOT}" && go run ./cmd/gen-unit-shape)

if [[ ! -f "${SHAPES_FILE}" ]]; then
  echo "ensure-repo: ERROR — shapes file not found at ${SHAPES_FILE}." >&2
  echo "ensure-repo: this is the hand-authored shape catalogue (chunk 13, task 2.x)" >&2
  echo "ensure-repo: and must exist before the shapes-load step can run." >&2
  exit 1
fi

if [[ ! -f "${SHAPES_UNITS_FILE}" ]]; then
  echo "ensure-repo: ERROR — unit-allowlist shape fragment not found at ${SHAPES_UNITS_FILE}" >&2
  echo "ensure-repo: after running 'go run ./cmd/gen-unit-shape'. Check cmd/gen-unit-shape" >&2
  echo "ensure-repo: writes this path (see design.md D3)." >&2
  exit 1
fi

echo "ensure-repo: loading shape catalogue into reserved graph <${SHACL_SHAPES_GRAPH}>..."

# Graph Store Protocol PUT (replace semantics) for the hand-authored shapes,
# then POST (append semantics) for the generated unit fragment. This
# PUT-then-POST order is deterministic and idempotent on re-run: every
# re-run of `make up` replaces the hand-authored shapes wholesale and then
# re-appends exactly the freshly regenerated unit fragment (never a stale
# one, since 3.2 regenerates it just above).
#
# Fallback (if PUT to the reserved shapes graph ever misbehaves on a given
# GraphDB version): a SPARQL 1.1 Update via POST /repositories/msr/statements
# with body:
#   DROP GRAPH <http://rdf4j.org/schema/rdf4j#SHACLShapeGraph> ;
#   INSERT DATA { GRAPH <http://rdf4j.org/schema/rdf4j#SHACLShapeGraph> { ... } }
# (the shapes file content inlined into the INSERT DATA block) achieves the
# same replace-then-append semantics without the Graph Store Protocol.

put_status="$(
  curl -sS -o /dev/null -w '%{http_code}' \
    -X PUT "${GRAPHDB_URL}/repositories/${REPO_ID}/rdf-graphs/service?graph=${SHACL_SHAPES_GRAPH_ENC}" \
    -H "Content-Type: text/turtle" \
    --data-binary "@${SHAPES_FILE}"
)"

if [[ "${put_status}" != "200" && "${put_status}" != "201" && "${put_status}" != "204" ]]; then
  echo "ensure-repo: failed to PUT ${SHAPES_FILE} into the shapes graph (HTTP ${put_status})" >&2
  exit 1
fi

post_status="$(
  curl -sS -o /dev/null -w '%{http_code}' \
    -X POST "${GRAPHDB_URL}/repositories/${REPO_ID}/rdf-graphs/service?graph=${SHACL_SHAPES_GRAPH_ENC}" \
    -H "Content-Type: text/turtle" \
    --data-binary "@${SHAPES_UNITS_FILE}"
)"

if [[ "${post_status}" != "200" && "${post_status}" != "201" && "${post_status}" != "204" ]]; then
  echo "ensure-repo: failed to POST ${SHAPES_UNITS_FILE} into the shapes graph (HTTP ${post_status})" >&2
  exit 1
fi

echo "ensure-repo: shape catalogue loaded successfully."
