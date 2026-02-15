.PHONY: test lint format typecheck check all

test:  ## Run unit tests
	python3 -m unittest test_main -v

lint:  ## Run ruff linter
	ruff check .

format:  ## Check code formatting
	ruff format --check .

format-fix:  ## Auto-fix formatting
	ruff format .

typecheck:  ## Run mypy strict type checking
	mypy --strict common_ui_usage/

check: lint format typecheck test  ## Run all checks (lint, format, typecheck, test)

all: check  ## Alias for check
