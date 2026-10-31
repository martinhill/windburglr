# Base images are pinned; bump them together. The Python builder and runtime stages share
# one base image so the virtualenv's interpreter matches the one it runs on.
ARG PYTHON_IMAGE=python:3.13.18-slim-bookworm

# Frontend
FROM node:24.22.2-bookworm-slim AS frontend
# sentry-cli, which uploads the source maps, verifies TLS against the system CA store; Node
# bundles its own, so the slim image doesn't ship one
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY vite.config.js ./
COPY src/ ./src/
# The source maps are uploaded under this release, the one the app reports to Sentry
ARG SENTRY_RELEASE
# The Sentry plugin uploads source maps when the token is set; they're deleted afterwards
# so they aren't served publicly
RUN --mount=type=secret,id=SENTRY_AUTH_TOKEN \
    SENTRY_AUTH_TOKEN="$(cat /run/secrets/SENTRY_AUTH_TOKEN 2>/dev/null)" \
    SENTRY_RELEASE="$SENTRY_RELEASE" npm run build \
    && find dist -name '*.map' -delete

# Python dependencies
FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project --no-editable

COPY pyproject.toml uv.lock README.md main.py ./
COPY app/ ./app/
# Always rebuild the project: uv's cached wheel is keyed on pyproject.toml, not the source
# files, so without this the persistent cache mount can install stale code
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --reinstall-package windburglr

# Runtime
FROM ${PYTHON_IMAGE}

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
# Migrations run from fly.toml's release_command. The binary is static, so the Alpine-based
# image's copy runs here; keep the version in step with dbmate in flake.nix.
COPY --from=ghcr.io/amacneil/dbmate:2.37.0 /usr/local/bin/dbmate /usr/local/bin/dbmate
ENV DBMATE_MIGRATIONS_DIR=/app/db/migrations DBMATE_NO_DUMP_SCHEMA=true
RUN useradd --system --uid 1000 --no-create-home app
WORKDIR /app

COPY --from=builder /app/.venv .venv/
COPY --from=frontend /app/dist ./dist/
COPY main.py ./
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/
COPY db/migrations/ ./db/migrations/

ARG SENTRY_RELEASE
ARG SENTRY_ENVIRONMENT=production
RUN test -n "$SENTRY_RELEASE" || { echo "ERROR: SENTRY_RELEASE not set"; exit 1; }
ENV SENTRY_RELEASE=$SENTRY_RELEASE SENTRY_ENVIRONMENT=$SENTRY_ENVIRONMENT

USER app
# Fly gives every machine of the app all its secrets. Only the release command needs the
# schema owner's credentials, so the web server never sees them.
CMD ["env", "-u", "MIGRATION_DATABASE_URL", "fastapi", "run"]
