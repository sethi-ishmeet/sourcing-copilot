# One command per check. `make check` is what CI runs on a pull request.
UV ?= uv
PY := $(UV) run

.PHONY: install dev ui ui-build lint test test-browser evals evals-live check reports clean

install:            ## Install backend and frontend dependencies
	$(UV) sync
	cd frontend && npm ci

dev:                ## Run the API on http://localhost:8000 (serves the built UI if present)
	$(PY) uvicorn sourcing_copilot.api.app:create_app --factory --reload --port 8000

ui:                 ## Run the UI dev server on http://localhost:5173 (proxies /api to :8000)
	cd frontend && npm run dev

ui-build:           ## Build the UI into frontend/dist
	cd frontend && npm run build

lint:               ## Ruff for Python, tsc for the UI
	$(PY) ruff check src tests evals
	$(PY) ruff format --check src tests evals
	cd frontend && npm run typecheck

test:               ## Unit, integration, API and data tests (no browser, no API key)
	$(PY) pytest -m "not browser" --junitxml=reports/tests/junit.xml

test-browser:       ## The one Playwright test. Needs `make ui-build` first.
	$(PY) pytest -m browser

evals:              ## Deterministic evals with the fake model; writes reports/evals/fake-model.*
	$(PY) python -m evals.run --model fake --trials 1 --out reports/evals

evals-live:         ## Evals against Gemini, 3 trials per case; needs GOOGLE_API_KEY
	$(PY) python -m evals.run --model gemini --trials 3 --out reports/evals

check: lint test evals   ## Everything a pull request must pass (browser test runs in CI too)

clean:
	rm -rf .pytest_cache .ruff_cache data/*.sqlite frontend/dist
