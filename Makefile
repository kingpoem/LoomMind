.PHONY: clean format lint log

format:
	uv run --group dev ruff format src scripts

lint:
	uv run --group dev ruff format --check src scripts
	uv run --group dev ruff check src scripts

log:
	uv run python scripts/export_log_txt.py

clean:
	rm -rf .ruff_cache
	find . -type d -name '__pycache__' -exec rm -rf {} +
	rm -rf log
