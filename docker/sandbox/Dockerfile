# syntax=docker/dockerfile:1
#
# Sandbox base image for the MSR knowledge-graph POC (chunk 1 / chunk 3 prep).
#
# This is deliberately minimal: a Python 3.12 runtime with pinned numpy and
# pandas, running as a fixed non-root user. Pool/exec logic (resource limits,
# per-task working dirs, the read-only ./data bind mount) lands in chunk 3 —
# this image only needs to build and let a non-root process `import numpy,
# pandas`.
#
# Build:  docker build -t msr-sandbox-base:latest -f docker/sandbox/Dockerfile docker/sandbox
# Verify: docker run --rm msr-sandbox-base:latest python -c "import numpy, pandas"
#         (must exit 0 while running as the non-root UID below)

FROM python:3.12-slim

# Pinned, exact, known-good stable 2.x releases. numpy/pandas 3.x exists
# upstream but is intentionally not adopted yet for this POC; bump these
# explicitly (not via a range) when the sandbox pool work in chunk 3 needs to.
ARG NUMPY_VERSION=2.5.1
ARG PANDAS_VERSION=2.3.3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# numpy/pandas ship manylinux wheels for cp312, so no compiler toolchain is
# needed here — keep the image minimal (no build-essential, no apt cache).
RUN pip install --no-cache-dir \
        "numpy==${NUMPY_VERSION}" \
        "pandas==${PANDAS_VERSION}"

# Fixed non-root UID/GID shared across the whole stack's bind-mount ownership
# contract (see design.md D5 / risk note on ./data host bind mount).
RUN groupadd --gid 10001 msr \
    && useradd --uid 10001 --gid msr --create-home --shell /usr/sbin/nologin msr

USER 10001:10001
WORKDIR /home/msr

CMD ["python3"]
