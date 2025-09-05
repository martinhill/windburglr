# WindBurglr Development Makefile

.PHONY: help setup dev backend frontend test test-backend test-frontend lint format type-check clean db-start db-stop db-restart db-status db-connect db-reset

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

db-start: ## Start PostgreSQL database
	pg_ctl -D .pgdata -l .pgdata/logfile start

db-stop: ## Stop PostgreSQL database
	pg_ctl -D .pgdata stop

db-restart: ## Restart PostgreSQL database
	pg_ctl -D .pgdata restart

db-status: ## Check PostgreSQL database status
	pg_ctl -D .pgdata status

db-connect: ## Connect to database
	psql -d windburglr

db-test: ## Test database connection
	@echo "Testing database connection..."
	@psql -d windburglr -c "SELECT version();" || echo "❌ Database connection failed"
	@psql -d windburglr -c "SELECT current_database(), current_user;" || echo "❌ Database query failed"

db-reset: ## Reset database (WARNING: destroys all data)
	@echo "⚠️  This will destroy all database data. Press Ctrl+C to cancel."
	@sleep 5
	pg_ctl -D .pgdata stop || true
	rm -rf .pgdata
	@echo "Run 'nix develop' or 'make setup' to reinitialize the database."