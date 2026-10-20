UV := uv run --frozen

.PHONY: check kernel-version lockcheck format lint typecheck imports test migration error-catalog

check: kernel-version lockcheck lint typecheck imports test

kernel-version:
	uv run --no-project --python 3.13 python -I .agents/skills/fast-ddd/scripts/check_kernel_version.py

lockcheck:
	uv lock --check

format:
	$(UV) ruff format .
	$(UV) ruff check --fix .

lint:
	$(UV) ruff format --check .
	$(UV) ruff check .

typecheck:
	$(UV) pyright

imports:
	$(UV) fast-ddd-check-packages --config .importlinter --source-root .
	$(UV) lint-imports --config .importlinter --no-cache

test:
	$(UV) coverage run -m pytest
	$(UV) coverage report

migration:
	$(UV) fast-ddd-alembic revision --autogenerate --head service@head \
		--version-path alembic/versions -m "$(name)"

error-catalog:
	PYTHONPATH=. $(UV) fast-ddd-error-catalog app.wiring --output error-catalog.json
