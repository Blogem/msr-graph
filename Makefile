# Makefile — msr-graph POC bootstrap orchestration.
#
# See openspec/changes/bootstrap-graph-infra/design.md and docker-compose.yml
# for the architecture this wires together. Bootstrap order:
#
#   make up         # one-time license preflight, start the stack, build the
#                   # extraction/sandbox images, wait for GraphDB, ensure the
#                   # "msr" repository exists (SHACL-enabled — see
#                   # openspec/changes/shacl-validation/design.md), and load
#                   # the SHACL shape catalogue into the reserved shapes
#                   # graph (scripts/ensure-repo.sh; idempotent, regenerates
#                   # the unit-allowlist fragment from
#                   # ontology/qudt-units.json on every run). If bringing up
#                   # on a pre-SHACL graphdb-data volume, ensure-repo.sh
#                   # fails with guidance — run `docker compose down -v`
#                   # first, then `make up` again.
#   make load-seed  # one-shot loader run: init-db then seed.
#   make load-nist  # ingest the vendored NIST SRD 27 fluoride CSVs (chains
#                   # after load-seed; additive, must run after seed).
#   make ingest     # one-shot extraction run: acquire -> manifest ->
#                   # normalize/segment -> documents (see
#                   # openspec/changes/ingest-archive-documents/design.md).
#   make link       # one-shot extraction run: link recognized spans to known
#                   # entities; writes msr:Mention triples + data/corpus/{report#}/
#                   # mentions.jsonl (see openspec/changes/ner-entity-linking/design.md).
#   make extract    # one-shot extraction run: LLM-assisted property-relation
#                   # extraction; writes msr:PropertyMeasurement/measurement_value
#                   # rows + data/corpus/{report#}/relations.jsonl (see
#                   # openspec/changes/extract-property-relations/design.md).
#   make mine       # one-shot extraction run: enumerate novel candidates ->
#                   # score -> triage -> write msr:ChangeProposal proposals +
#                   # auto-accepted instances (see
#                   # openspec/changes/mine-ontology-candidates/design.md).
#   make test       # go test ./... with the GraphDB and sandbox Docker
#                   # acceptance gates enabled.
#   make down       # stop the stack and remove its volumes.
#   make chat       # manual-verification REPL for POST /api/chat (cmd/chatcli),
#                   # against the published http://localhost:8080/api/chat —
#                   # run this against a stack already brought up with `make up`.
#   make demo-density # one-shot chatcli run of the canonical FLiBe density
#                     # question, for a quick smoke test of the same endpoint.
#   make checkpoint  # POST /api/checkpoints against the running server
#                     # (LABEL, default "demo") — captures the whole store
#                     # (GraphDB TriG export of all named graphs + a SQLite
#                     # snapshot + the ontology version) under
#                     # data/checkpoints/{LABEL}/ (see
#                     # openspec/changes/apply-ontology-changes/design.md).
#   make restore     # POST /api/checkpoints/{LABEL}/restore against the
#                     # running server — clears and re-imports the graph and
#                     # swaps the SQLite file back to the checkpointed copy.

.PHONY: up down load-seed load-nist ingest link extract mine test chat demo-density checkpoint restore

# GraphDB's published host port (see docker-compose.yml, service "graphdb").
GRAPHDB_URL ?= http://localhost:7200

# The msr-graph server's published base URL (see cmd/server/config.go's
# SERVER_ADDR, default ":8080", and docker-compose.yml, service "server").
# Overridable so checkpoint/restore can target a differently-configured
# server without editing this file.
SERVER_URL ?= http://localhost:8080

# Checkpoint label used by `make checkpoint` / `make restore`; override with
# e.g. `make checkpoint LABEL=before-solubility`.
LABEL ?= demo

# Free-license request page referenced by GraphDB 11.x's own licensing docs
# (https://graphdb.ontotext.com/documentation/11.4/licensing.html):
# GraphDB Free requires a license file requested from Graphwise/Ontotext
# before first use.
LICENSE_REQUEST_URL := https://www.ontotext.com/products/graphdb/

up:
	@# PREFLIGHT — fail fast, before starting any container, if the
	@# requested free license file is missing from the repo root.
	@if [ ! -f graphdb.license ]; then \
		echo "error: graphdb.license not found in repo root." >&2; \
		echo "GraphDB 11.x requires a license file. Request a free one at:" >&2; \
		echo "  $(LICENSE_REQUEST_URL)" >&2; \
		echo "then save it as graphdb.license in the repo root and re-run 'make up'." >&2; \
		exit 1; \
	fi
	@echo "==> starting graphdb + server"
	docker compose up -d
	@echo "==> building server, extraction, loader, and sandbox base images"
	@# `loader` is in the "tools" profile, so it is skipped by a bare
	@# `docker compose build`; naming it explicitly keeps its image fresh on
	@# every `make up` (otherwise `docker compose run loader` reuses a stale
	@# image and never picks up loader code changes, e.g. new subcommands).
	docker compose build server extraction loader
	@# Tag must match the server's MSR_SANDBOX_IMAGE default (internal/sandbox,
	@# see docker-compose.yml "server" service) so the pool's configured image
	@# reference resolves to this build.
	docker build -t msr-sandbox-base:latest docker/sandbox
	@echo "==> waiting for graphdb to report healthy at $(GRAPHDB_URL)"
	@timeout=180; elapsed=0; \
	until curl -fsS "$(GRAPHDB_URL)/rest/repositories" >/dev/null 2>&1; do \
		if [ "$$elapsed" -ge "$$timeout" ]; then \
			echo "error: graphdb did not become healthy within $${timeout}s" >&2; \
			exit 1; \
		fi; \
		sleep 3; elapsed=$$((elapsed + 3)); \
	done
	@echo "==> graphdb is healthy"
	@echo "==> ensuring GraphDB repository 'msr' exists"
	GRAPHDB_URL=$(GRAPHDB_URL) scripts/ensure-repo.sh

down:
	docker compose down -v

load-seed:
	@echo "==> running loader init-db"
	docker compose run --rm loader /app/loader init-db
	@echo "==> running loader seed"
	docker compose run --rm loader /app/loader seed

load-nist: load-seed
	@echo "==> running loader nist"
	docker compose run --rm -e MSR_NIST_DIR=/data/nist loader /app/loader nist

ingest:
	@echo "==> running extraction ingest (acquire -> manifest -> normalize/segment -> documents)"
	docker compose run --rm extraction ingest

link:
	@echo "==> running extraction link (seed matcher -> link segments -> disambiguate -> write mentions + mentions.jsonl)"
	docker compose run --rm extraction link

extract:
	@echo "==> running extraction extract (LLM-assisted property-relation extraction -> write measurements + relations.jsonl)"
	docker compose run --rm extraction extract

mine:
	@echo "==> running extraction mine (enumerate novel candidates -> score -> triage -> write proposals + auto-accepted instances)"
	docker compose run --rm extraction mine

test:
	@echo "==> running go test with the GraphDB and sandbox Docker acceptance gates enabled (GRAPHDB_REQUIRED=1, SANDBOX_DOCKER_REQUIRED=1)"
	GRAPHDB_REQUIRED=1 SANDBOX_DOCKER_REQUIRED=1 go test ./...

chat:
	@echo "==> starting chatcli REPL against http://localhost:8080/api/chat (run 'make up' first)"
	go run ./cmd/chatcli

demo-density:
	@echo "==> running chatcli one-shot: canonical FLiBe density question"
	go run ./cmd/chatcli -q "What is the density of FLiBe (the LiF-BeF2 66-34 mol% melt) at 900 K?"

checkpoint:
	@echo "==> creating checkpoint '$(LABEL)' via $(SERVER_URL)/api/checkpoints (run 'make up' first)"
	curl -sS -X POST "$(SERVER_URL)/api/checkpoints" \
		-H 'Content-Type: application/json' \
		-d '{"label":"$(LABEL)"}'

restore:
	@echo "==> restoring checkpoint '$(LABEL)' via $(SERVER_URL)/api/checkpoints/$(LABEL)/restore (run 'make up' first)"
	curl -sS -X POST "$(SERVER_URL)/api/checkpoints/$(LABEL)/restore"
