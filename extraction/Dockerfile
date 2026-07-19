# syntax=docker/dockerfile:1
#
# Extraction image for the MSR knowledge-graph POC (chunk 1 scaffold,
# extended in chunk 5 for in-container corpus acquisition).
#
# This installs the `msr_extraction` pyproject package and runs its
# `msr-extraction` console script as a fixed non-root user. Chunk 5 adds
# `git` + `git-lfs` so the `acquire` step can `git clone` the msr-archive
# corpus directly inside this container (network + GraphDB enabled, unlike
# the sandboxes) — see openspec/changes/ingest-archive-documents/design.md D1.
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

# git + git-lfs for in-container corpus acquisition (the `acquire` step
# clones openmsr/msr-archive with GIT_LFS_SKIP_SMUDGE=1; see design.md D1).
# `git lfs install --system` registers the LFS filters once for all users
# without requiring a per-repo `git lfs install`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git git-lfs \
    && git lfs install --system \
    && rm -rf /var/lib/apt/lists/*

# Copy only the project metadata and package sources needed to build the
# package (build context is extraction/, see the `docker build` line above).
COPY pyproject.toml ./
COPY src ./src

# hatchling ships pure Python wheels for this package, so no compiler
# toolchain is needed here — keep the image minimal.
RUN pip install --no-cache-dir .

# Fixed non-root UID/GID shared across the whole stack's bind-mount ownership
# contract (see design.md D5 / risk note on ./data host bind mount).
RUN groupadd --gid 10001 msr \
    && useradd --uid 10001 --gid msr --create-home --shell /usr/sbin/nologin msr

USER 10001:10001

ENTRYPOINT ["msr-extraction"]
CMD ["--help"]
