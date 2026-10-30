# WindBurglr shared development database (see scripts/db.sh)

.PHONY: help db-up db-down db-status db-connect db-reset-dev db-test-clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

db-up: ## Start the shared PostgreSQL cluster (builds template and dev database if needed)
	scripts/db.sh up

db-down: ## Stop the shared PostgreSQL cluster
	scripts/db.sh down

db-status: ## Show cluster state and databases
	scripts/db.sh status

db-connect: ## Connect to the development database
	psql -d windburglr_dev

db-reset-dev: ## Recreate the development database from the current schema (destroys its data)
	scripts/db.sh reset-dev

db-test-clean: ## Drop test databases left behind by aborted test runs
	scripts/db.sh test-clean
