# Base images are pinned; bump them together. The builder and runtime stages share one
# base image so the virtualenv's interpreter matches the one it runs on.
ARG PYTHON_IMAGE=python:3.13.18-slim-bookworm

FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project --no-editable

COPY pyproject.toml uv.lock ./
COPY windscraper/ ./windscraper/
# Always rebuild the project: uv's cached wheel is keyed on pyproject.toml, not the source
# files, so without this the persistent cache mount can install stale code
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --reinstall-package windscraper

FROM ${PYTHON_IMAGE}

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
RUN useradd --system --uid 1000 --no-create-home app
WORKDIR /app

COPY --from=builder /app/.venv .venv/

# Station config isn't in the image: it's read from the SCRAPER_CONFIG secret (see fly-deploy.sh)
ARG SENTRY_RELEASE
ARG SENTRY_ENVIRONMENT=production
RUN test -n "$SENTRY_RELEASE" || { echo "ERROR: SENTRY_RELEASE not set"; exit 1; }
ENV SENTRY_RELEASE=$SENTRY_RELEASE SENTRY_ENVIRONMENT=$SENTRY_ENVIRONMENT

USER app
CMD ["scraper"]
