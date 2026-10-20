UV := uv run --frozen --package example-service
KERNEL_VERSION_SCRIPT := template/.agents/skills/fast-ddd/scripts/check_kernel_version.py

.PHONY: check tooling template-check template-ownership template-references

check:
	$(MAKE) tooling
	$(MAKE) -C kernel check
	$(MAKE) -C example check
	$(MAKE) template-check

tooling:
	$(UV) ruff format --check scripts template $(KERNEL_VERSION_SCRIPT)
	$(UV) ruff check scripts template $(KERNEL_VERSION_SCRIPT)
	$(UV) pyright --project example/pyrightconfig.json scripts $(KERNEL_VERSION_SCRIPT)
	$(UV) pre-commit run check-merge-conflict --all-files
	$(UV) python scripts/check_versions.py

template-check:
	$(UV) python scripts/check_template.py --snapshot

template-ownership:
	$(UV) python scripts/check_template.py --update-ownership

template-references:
	$(UV) python scripts/check_template.py --sync-references
