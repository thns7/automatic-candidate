.PHONY: install install-browser init doctor discover apply status export test lint

install:
	pip install -e .

install-browser:
	pip install -e ".[browser]"
	python -m playwright install chromium

init:
	candidate init

doctor:
	candidate doctor

discover:
	candidate discover

apply:
	candidate apply --limit 5

status:
	candidate status

export:
	candidate export --format csv

test:
	pytest -q

lint:
	ruff check src tests
