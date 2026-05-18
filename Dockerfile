# One image, every role. The role is the *command*, not the image:
#   wildfire-local | wildfire-producer | wildfire-consumer
# (compose / k8s override `command`). This is the container expression of
# the seam work — one codebase, the profile + command pick the topology.

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# uv for fast, locked installs.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Deps first (cached layer): only re-resolved when the lock/manifest change.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Project source.
COPY src/ ./src/
COPY main.py ./
RUN uv sync --frozen --no-dev

# Run as non-root (a seasoned-reviewer baseline for container security).
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PATH="/app/.venv/bin:${PATH}"

# Default to the collapsed single executable. compose/k8s override this
# with wildfire-producer / wildfire-consumer for the split topology.
CMD ["wildfire-local"]
