UV := uv run --frozen

.PHONY: check lockcheck format lint typecheck imports test

check: lockcheck lint typecheck imports test

lockcheck:
	uv lock --check

format:
	$(UV) ruff format src tests
	$(UV) ruff check --fix src tests

lint:
	$(UV) ruff format --check src tests
	$(UV) ruff check src tests

typecheck:
	$(UV) pyright

imports:
	$(UV) fast-ddd-check-packages --config pyproject.toml --source-root src
	cd src && $(UV) lint-imports --config ../pyproject.toml --no-cache

test:
	$(UV) coverage run -m pytest
	$(UV) coverage report
