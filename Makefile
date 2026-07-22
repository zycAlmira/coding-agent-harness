.PHONY: test run lint
test:
	uv run pytest -q
run:
	uv run harness serve
lint:
	uv run ruff check src tests
