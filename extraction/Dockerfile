# syntax=docker/dockerfile:1
#
# Extraction image for the MSR knowledge-graph POC (chunk 1 scaffold).
#
# This is deliberately minimal: it installs the `msr_extraction` pyproject
# scaffold (hatchling build backend, no dependencies) and runs its
# `msr-extraction` console script as a fixed non-root user. The real
# extraction pipeline (chunks 5-8) replaces the package contents later;
# this Dockerfile only needs to prove the image builds and the entry point
# resolves.
#
# Build:  docker build -t msr-extraction:latest -f extraction/Dockerfile extraction
# Verify: docker run --rm msr-extraction:latest
#         (defaults to `msr-extraction --help`; must exit 0 as the non-root UID below)

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy only the project metadata and package sources needed to build the
# scaffold (build context is extraction/, see the `docker build` line above).
COPY pyproject.toml ./
COPY src ./src

# hatchling ships pure Python wheels for this scaffold (no dependencies), so
# no compiler toolchain is needed here — keep the image minimal.
RUN pip install --no-cache-dir .

# Fixed non-root UID/GID shared across the whole stack's bind-mount ownership
# contract (see design.md D5 / risk note on ./data host bind mount).
RUN groupadd --gid 10001 msr \
    && useradd --uid 10001 --gid msr --create-home --shell /usr/sbin/nologin msr

USER 10001:10001

ENTRYPOINT ["msr-extraction"]
CMD ["--help"]
