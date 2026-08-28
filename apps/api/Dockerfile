# syntax=docker/dockerfile:1
# check=error=true
#
# FastAPI backend. Targets:
#   development — uv + dev deps + --reload (docker-compose.dev.yml)
#   production  — slim runtime with only the resolved venv (docker-compose.yml)
#
# Build context is the repo root — the uv workspace lockfile lives there.

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.10.10

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ── base: shared runtime foundation ──────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Berlin
WORKDIR /app
# curl for the compose healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# ── development ──────────────────────────────────────────────────────────────
FROM base AS development
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
COPY ruff.toml ./
COPY apps/api/pyproject.toml ./apps/api/
RUN uv sync --frozen --package shop2tax-api
COPY apps/api/app ./apps/api/app
COPY apps/api/alembic ./apps/api/alembic
COPY apps/api/alembic.ini ./apps/api/
WORKDIR /app/apps/api
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── build: resolve + install production dependencies into /app/.venv ─────────
FROM base AS build
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml ./apps/api/
# --no-install-project: third-party deps only; the app runs from the copied source tree.
RUN uv sync --frozen --no-dev --no-install-project --package shop2tax-api

# ── production: runtime image ────────────────────────────────────────────────
FROM base AS production
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app
# Receipt storage mount point: a fresh named volume inherits this ownership.
RUN mkdir -p /data/receipts && chown app:app /data/receipts
COPY --from=build --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY --chown=app:app apps/api/app ./apps/api/app
COPY --chown=app:app apps/api/alembic ./apps/api/alembic
COPY --chown=app:app apps/api/alembic.ini ./apps/api/
WORKDIR /app/apps/api
USER app
EXPOSE 8000
# The API is only reachable on the internal network via the Nuxt proxy / Caddy.
# --proxy-headers + private ranges: request.client.host becomes the real client IP
# (rate limiting) while X-Forwarded-For from outside the internal network is ignored.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--no-server-header", "--proxy-headers", \
     "--forwarded-allow-ips", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"]
