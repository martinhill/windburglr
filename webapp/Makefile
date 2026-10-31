# WindBurglr Development Makefile

.PHONY: help install dev backend frontend build test test-backend test-frontend lint format type-check clean db-up db-down db-status db-connect db-reset-dev

PORT ?= 8000

# Exports .env (if present) to the backend, which doesn't read it itself
LOAD_ENV = set -a; if [ -f .env ]; then . ./.env; fi; set +a

help: ## Show this help message
	@echo "WindBurglr Development Commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install: ## Install Python and Node.js dependencies
	uv sync
	npm install

dev: ## Start the backend with Vite hot reloading (Ctrl-C stops both)
	@$(LOAD_ENV); export DEV_MODE=true; \
	uv run fastapi dev --host 0.0.0.0 --port $(PORT) & backend=$$!; \
	trap 'kill $$backend 2>/dev/null; wait $$backend 2>/dev/null' EXIT INT TERM; \
	npm run dev

backend: ## Start the backend, serving the built frontend from dist/ (run `make build` first)
	@$(LOAD_ENV); uv run fastapi dev --host 0.0.0.0 --port $(PORT)

frontend: ## Start frontend development server
	npm run dev

test: ## Run all tests
	pytest -v
	npm run test:run

test-backend: ## Run Python tests
	pytest -v

test-frontend: ## Run frontend tests
	npm run test:run

lint: ## Lint Python code
	ruff check .

format: ## Format Python code
	ruff format .

type-check: ## Type check Python code
	pyright

clean: ## Clean up generated files
	rm -rf dist/ build/ htmlcov/ .coverage .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: ## Build frontend for production
	npm run build

db-up: ## Start the shared PostgreSQL cluster (builds template and dev database if needed)
	../scripts/db.sh up

db-down: ## Stop the shared PostgreSQL cluster
	../scripts/db.sh down

db-status: ## Show cluster state and databases
	../scripts/db.sh status

db-connect: ## Connect to the development database
	psql -d windburglr_dev

db-reset-dev: ## Recreate the development database from the current schema (destroys its data)
	../scripts/db.sh reset-dev
