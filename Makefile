.PHONY: check lint test

PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff

check: lint test

lint:
	$(RUFF) check .

test:
	$(PYTHON) -m unittest discover -s tests -v
