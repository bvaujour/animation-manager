PYTHON ?= python

.PHONY: install check test lint verify run clean

install:
	bash scripts/setup_dev.sh

check:
	$(PYTHON) scripts/static_audit.py
	$(PYTHON) manage.py check

test:
	$(PYTHON) manage.py test animateurs.tests

lint:
	ruff check config animateurs scripts

verify:
	bash scripts/verify.sh

run:
	$(PYTHON) manage.py runserver

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
	rm -rf staticfiles .ruff_cache .pytest_cache
