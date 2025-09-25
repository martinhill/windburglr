FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app

# Install Python dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project --no-editable

# Sync the project
COPY pyproject.toml uv.lock ./
COPY windscraper ./windscraper/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# Capture git SHA for Sentry release tracking
ARG SENTRY_RELEASE
ARG SENTRY_ENVIRONMENT=production
RUN if [ -z "$SENTRY_RELEASE" ]; then echo "ERROR: SENTRY_RELEASE not set"; exit 1; fi
RUN echo SENTRY_RELEASE=$SENTRY_RELEASE >> .env.sentry
RUN echo SENTRY_ENVIRONMENT=$SENTRY_ENVIRONMENT >> .env.sentry

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv/
COPY --from=builder /app/.env.sentry .

# Copy application files explicitly to avoid overwriting dist/
# COPY windscraper /app/windscraper/
ARG SCRAPER_CONFIG_FILE=windburglr.prod.toml
COPY ${SCRAPER_CONFIG_FILE} /app/windburglr.toml

ENV PATH="/app/.venv/bin:$PATH"

CMD ["scraper"]
