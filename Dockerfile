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

# ---- frontend ------------------------------------------------------------
# Builds the SvelteKit static assets that cmd/server embeds via
# `//go:embed all:build` (webapp/embed.go). Must run before the Go build
# stage below so the embedded directory has real content at compile time
# (design.md D1, "Embed requires build-before-compile").
FROM node:22 AS frontend

WORKDIR /webapp

COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci

COPY webapp/ ./
RUN npm run build

# ---- builder -----------------------------------------------------------
FROM golang:1.26 AS builder

WORKDIR /src

# Dependency layer first so `go mod download` is cached across source-only
# changes.
COPY go.mod go.sum ./
RUN go mod download

COPY . .

# Overlay the real frontend build on top of the committed placeholder
# (webapp/build/index.html) brought in by `COPY . .` above, so
# `//go:embed all:build` picks up the actual built assets.
COPY --from=frontend /webapp/build ./webapp/build

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
