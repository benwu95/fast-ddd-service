UV := uv run --frozen --package example-service

.PHONY: check tooling template-check template-ownership

check:
	$(MAKE) tooling
	$(MAKE) -C kernel check
	$(MAKE) -C example check
	$(MAKE) template-check

tooling:
	$(UV) ruff format --check scripts template
	$(UV) ruff check scripts template
	$(UV) pyright --project example/pyrightconfig.json scripts
	$(UV) pre-commit run check-merge-conflict --all-files
	$(UV) python scripts/check_versions.py

template-check:
	$(UV) python scripts/check_template.py --snapshot

template-ownership:
	$(UV) python scripts/check_template.py --update-ownership
