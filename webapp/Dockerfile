FROM python:3.13 AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs

# Install Python dependencies
RUN pip install poetry
RUN poetry config virtualenvs.in-project true
COPY pyproject.toml poetry.lock ./
RUN poetry install

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

CMD ["/app/.venv/bin/fastapi", "run"]
