# syntax=docker/dockerfile:1
#
# Multi-stage build for the msr-graph Go binaries: `server` (HTTP API) and
# `loader` (seed/init-db one-shot tool). One image, two compose services
# (design.md D5) — compose's `loader` service overrides `command:` to run
# `/app/loader ...` instead of the default entrypoint below.
#
# Pure-Go build: the SQLite driver is modernc.org/sqlite (cgo-free), so
# CGO_ENABLED=0 and a distroless-static final stage are sufficient — no gcc,
# no libc, no alpine needed.
#
# Build:  docker build -t msr-graph:latest .
# Run:    docker run --rm msr-graph:latest                       # server
#         docker run --rm msr-graph:latest /app/loader seed ...  # loader

# ---- builder -----------------------------------------------------------
FROM golang:1.26 AS builder

WORKDIR /src

# Dependency layer first so `go mod download` is cached across source-only
# changes.
COPY go.mod go.sum ./
RUN go mod download

COPY . .

RUN CGO_ENABLED=0 go build -o /out/server ./cmd/server
RUN CGO_ENABLED=0 go build -o /out/loader ./cmd/loader

# ---- final ---------------------------------------------------------------
FROM gcr.io/distroless/static-debian12

WORKDIR /app

COPY --from=builder /out/server /app/server
COPY --from=builder /out/loader /app/loader

# Seed ontology TTLs: `loader seed` reads MSR_ONTOLOGY_DIR (default
# "ontology"), resolved relative to WORKDIR /app -> /app/ontology.
COPY ontology/ /app/ontology/

# Fixed non-root UID shared across the whole stack's bind-mount ownership
# contract (design.md D5). distroless-static has no /etc/passwd entry for
# this UID; a numeric USER doesn't require one.
USER 10001:10001

# Default entrypoint runs the server; the compose `loader` service overrides
# `command:` to invoke /app/loader with its subcommand instead.
ENTRYPOINT ["/app/server"]
