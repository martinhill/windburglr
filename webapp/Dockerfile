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
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv/
COPY --from=builder /app/dist ./dist/
COPY . .
CMD ["/app/.venv/bin/fastapi", "run"]
