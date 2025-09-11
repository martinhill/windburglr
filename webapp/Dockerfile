FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Install Node.js
RUN apt-get update && apt-get install -y curl
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs

# Install Python dependencies
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Install frontend dependencies and build
COPY package.json package-lock.json ./
RUN npm install
COPY src/ ./src/
COPY vite.config.js ./
RUN --mount=type=secret,id=SENTRY_AUTH_TOKEN \
    SENTRY_AUTH_TOKEN="$(cat /run/secrets/SENTRY_AUTH_TOKEN)" npm run build

# Capture git SHA for Sentry release tracking
ARG SENTRY_RELEASE
ARG SENTRY_ENVIRONMENT=production
RUN if [ -z "$SENTRY_RELEASE" ]; then echo "ERROR: SENTRY_RELEASE not set"; exit 1; fi
RUN echo SENTRY_RELEASE=$SENTRY_RELEASE >> .env.sentry
RUN echo SENTRY_ENVIRONMENT=$SENTRY_ENVIRONMENT >> .env.sentry

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv/
COPY --from=builder /app/dist ./dist/
COPY --from=builder /app/.env.sentry .

# Copy application files explicitly to avoid overwriting dist/
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/
COPY main.py .

ENV PATH="/app/.venv/bin:$PATH"

CMD ["fastapi", "run"]
