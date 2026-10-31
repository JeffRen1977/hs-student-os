# High School Student OS — local development commands.
# Emulator hosts default to the ports in server/firebase.json and can be overridden
# from the environment (e.g. `FIRESTORE_EMULATOR_HOST=127.0.0.1:8181 make seed`).

SERVER_DIR := server
WEB_DIR := web
API_PORT ?= 8787
WEB_PORT ?= 8000
FIREBASE_PROJECT ?= demo-hs-student-os
FIRESTORE_EMULATOR_HOST ?= 127.0.0.1:8080
FIREBASE_AUTH_EMULATOR_HOST ?= 127.0.0.1:9099
EMULATOR_ENV := FIRESTORE_EMULATOR_HOST=$(FIRESTORE_EMULATOR_HOST) \
	FIREBASE_AUTH_EMULATOR_HOST=$(FIREBASE_AUTH_EMULATOR_HOST) \
	HSOS_GCP_PROJECT_ID=$(FIREBASE_PROJECT)

.PHONY: help install dev server server-memory web emulators seed typecheck lint format test \
	test-unit test-contract test-emulator test-web check

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  %-15s %s\n", $$1, $$2}'

install: ## Install backend dependencies with uv
	cd $(SERVER_DIR) && uv sync

dev: ## Run API (auto-reload) and static web server together
	@trap 'kill 0' INT TERM EXIT; \
	$(MAKE) --no-print-directory server & \
	$(MAKE) --no-print-directory web & \
	wait

server: ## Run the API (+ local worker loop) against the emulators on :$(API_PORT)
	cd $(SERVER_DIR) && $(EMULATOR_ENV) uv run uvicorn app.main:app --reload --port $(API_PORT)

server-memory: ## Run the API over an in-memory store seeded with fixtures (no Java needed)
	cd $(SERVER_DIR) && $(EMULATOR_ENV) HSOS_STORAGE_PROVIDER=memory \
		uv run uvicorn app.main:app --port $(API_PORT)

web: ## Serve web/ on :$(WEB_PORT) (add ?demo=true for demo mode)
	python3 -m http.server $(WEB_PORT) -d $(WEB_DIR)

emulators: ## Start Firebase Auth + Firestore emulators (requires Java 11+)
	cd $(SERVER_DIR) && firebase emulators:start --only auth,firestore --project $(FIREBASE_PROJECT)

seed: ## Seed running emulators with synthetic students
	cd $(SERVER_DIR) && $(EMULATOR_ENV) uv run python -m scripts.seed_emulator

typecheck: ## mypy (strict) over app/
	cd $(SERVER_DIR) && uv run mypy app/

lint: ## ruff lint + format check
	cd $(SERVER_DIR) && uv run ruff check . && uv run ruff format --check .

format: ## ruff autoformat
	cd $(SERVER_DIR) && uv run ruff check --fix . && uv run ruff format .

test: ## All backend tests (emulator tests skip unless emulators are configured)
	cd $(SERVER_DIR) && uv run pytest

test-unit:
	cd $(SERVER_DIR) && uv run pytest tests/unit

test-contract:
	cd $(SERVER_DIR) && uv run pytest tests/contract

test-emulator: ## Start emulators, seed, and run emulator tests, then shut down
	cd $(SERVER_DIR) && firebase emulators:exec --only auth,firestore --project $(FIREBASE_PROJECT) \
		"$(EMULATOR_ENV) uv run pytest tests/emulator"

test-web: ## Frontend data-provider tests (node:test, no npm install needed)
	node --test $(WEB_DIR)/tests/

check: lint typecheck test test-web ## Everything that must pass before committing
