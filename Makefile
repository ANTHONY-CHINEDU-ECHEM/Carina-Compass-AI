PYTHON ?= python3
export PYTHONPATH := backend:.

.PHONY: help install install_ml seed serve frontend demo_build ingest ingest_quick ingest_trials build_index stats up_local \
        test coverage lint format typecheck eval eval_gate eval_live check up down logs readme_check clean

help:
	@grep -E '^[a-z_]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install: ## Install Python (with dev and LLM extras) and frontend dependencies
	$(PYTHON) -m pip install -e ".[dev,llm]"
	cd frontend && npm install

install_ml: ## Add BGE embeddings, the cross encoder reranker, Qdrant and Redis clients
	$(PYTHON) -m pip install -e ".[ml,stores]"

seed: ## Index the verified seed snapshot in seconds
	$(PYTHON) -m ingestion.cli seed

serve: ## Run the API on port 8000 with reload
	$(PYTHON) -m uvicorn carina.main:app --reload --port 8000

frontend: ## Run the clinician interface on port 5173
	cd frontend && npm run dev

demo_build: ## Rebuild the standalone browser demo from the seed snapshot and rule files
	$(PYTHON) scripts/build_demo.py

ingest: ## Harvest every real source and build the full index (several hours)
	$(PYTHON) -m ingestion.cli run

ingest_quick: ## Capped harvest for development (500 documents per source)
	$(PYTHON) -m ingestion.cli run --limit 500

ingest_trials: ## Refresh ClinicalTrials.gov records only
	$(PYTHON) -m ingestion.cli run clinical_trials

build_index: ## Rebuild the index from existing harvest checkpoints
	$(PYTHON) -m ingestion.cli build

stats: ## Show the index manifest
	$(PYTHON) -m ingestion.cli stats

test: ## Unit, pipeline and API tests
	$(PYTHON) -m pytest

coverage: ## Tests with a coverage report
	$(PYTHON) -m pytest --cov --cov-report=term-missing

lint: ## Ruff lint and format check
	ruff check .
	ruff format --check .

format: ## Apply ruff formatting and safe fixes
	ruff check . --fix
	ruff format .

typecheck: ## Mypy over the backend, ingestion and evaluation packages
	mypy backend/carina ingestion evaluation

eval: ## Offline evaluation on the seed index
	$(PYTHON) -m evaluation.harness offline

eval_gate: ## Offline evaluation that fails when any threshold is missed
	$(PYTHON) -m evaluation.harness gate

eval_live: ## Evaluation against the live index and configured model
	$(PYTHON) -m evaluation.harness live

readme_check: ## Fail if the README contains hyphens or dashes in prose
	$(PYTHON) scripts/check_readme.py

check: lint typecheck test eval_gate readme_check ## Everything CI runs

up: ## Start the full container stack
	docker compose up --build -d

up_local: ## Start the stack with a local Ollama model as well
	docker compose --profile local up --build -d

down: ## Stop the container stack
	docker compose down

logs: ## Follow API logs
	docker compose logs -f api

clean: ## Remove caches and local build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache frontend/dist **/__pycache__
