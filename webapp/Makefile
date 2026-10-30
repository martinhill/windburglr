# WindBurglr Development Makefile

.PHONY: help setup dev backend frontend test test-backend test-frontend lint format type-check clean db-up db-down db-status db-connect db-reset-dev

help: ## Show this help message
	@echo "WindBurglr Development Commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

setup: ## Set up development environment
	./dev-setup.sh

dev: ## Start both backend and frontend in development mode
	@echo "Starting development servers..."
	@./start.sh &
	@sleep 2
	@npm run dev

backend: ## Start backend server
	uvicorn main:app --host 0.0.0.0 --port 8000 --reload

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

install: ## Install all dependencies
	uv pip install -e .
	uv pip install -e ".[dev]"
	npm install

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
