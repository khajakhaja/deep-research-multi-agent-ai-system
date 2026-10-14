# Deep Research AI - developer task runner.
# Works on Linux/macOS and in CI. On Windows, use the venv directly or WSL.

PYTHON ?= python
VENV   ?= .venv

.PHONY: help install test demo init-db run-api run-ui eval docker-up docker-down clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install backend + frontend dependencies
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r backend/requirements.txt
	$(VENV)/bin/pip install -r frontend/requirements.txt

test: ## Run the test suite
	$(VENV)/bin/python -m pytest backend/tests/ -v

demo: ## Run the offline end-to-end demo (no API keys needed)
	$(VENV)/bin/python scripts/demo.py

init-db: ## Create the database schema
	$(VENV)/bin/python scripts/init_db.py

run-api: ## Start the FastAPI backend (http://localhost:8000)
	$(VENV)/bin/python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload

run-ui: ## Start the Streamlit frontend (http://localhost:8501)
	$(VENV)/bin/python -m streamlit run frontend/app.py

eval: ## Run the evaluation benchmark (requires real API keys)
	$(VENV)/bin/python scripts/run_eval.py

docker-up: ## Build and start the full stack with docker compose
	docker compose up --build

docker-down: ## Stop the stack
	docker compose down

clean: ## Remove caches and local data
	rm -rf data .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
