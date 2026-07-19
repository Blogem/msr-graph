# Makefile — msr-graph POC bootstrap orchestration.
#
# See openspec/changes/bootstrap-graph-infra/design.md and docker-compose.yml
# for the architecture this wires together. Bootstrap order:
#
#   make up         # one-time license preflight, start the stack, build the
#                   # extraction/sandbox images, wait for GraphDB, ensure the
#                   # "msr" repository exists.
#   make load-seed  # one-shot loader run: init-db then seed.
#   make load-nist  # ingest the vendored NIST SRD 27 fluoride CSVs (chains
#                   # after load-seed; additive, must run after seed).
#   make ingest     # one-shot extraction run: acquire -> manifest ->
#                   # normalize/segment -> documents (see
#                   # openspec/changes/ingest-archive-documents/design.md).
#   make test       # go test ./... with the GraphDB and sandbox Docker
#                   # acceptance gates enabled.
#   make down       # stop the stack and remove its volumes.

.PHONY: up down load-seed load-nist ingest test

# GraphDB's published host port (see docker-compose.yml, service "graphdb").
GRAPHDB_URL ?= http://localhost:7200

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
	@echo "==> building extraction and sandbox base images"
	docker compose build server extraction
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

test:
	@echo "==> running go test with the GraphDB and sandbox Docker acceptance gates enabled (GRAPHDB_REQUIRED=1, SANDBOX_DOCKER_REQUIRED=1)"
	GRAPHDB_REQUIRED=1 SANDBOX_DOCKER_REQUIRED=1 go test ./...
