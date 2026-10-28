# Parsewright developer commands. Run `make setup` once after cloning.
.PHONY: setup up down logs test lint security

VENV := .venv
BIN := $(VENV)/bin

setup:
	@[ -f .env ] || { cp .env.example .env && echo "Created .env from .env.example: fill in the placeholders."; }
	@chmod 600 .env
	python3 -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e 'engine[dev]'
	$(BIN)/pre-commit install
	cd web && npm ci

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

test:
	$(BIN)/pytest engine/tests tests
	cd web && npm run build && npm run test:e2e

lint:
	$(BIN)/pre-commit run --all-files
	cd web && npm run lint && npm run typecheck

# Needs semgrep and gitleaks on PATH (see README, "Running tests and security checks").
security:
	$(BIN)/bandit -c engine/pyproject.toml -r engine scripts
	semgrep scan --config p/default --error --metrics=off --quiet
	$(BIN)/pip-audit --skip-editable
	cd web && npm audit --audit-level=moderate
	gitleaks git --redact --verbose .
