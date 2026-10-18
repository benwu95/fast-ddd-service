.PHONY: check

check:
	$(MAKE) -C kernel check
	$(MAKE) -C example check
