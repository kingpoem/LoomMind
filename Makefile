.PHONY: run clean format lint log graph

run:
	uv run python src/main.py --cli

format:
	uv run --group dev ruff format src scripts

lint:
	uv run --group dev ruff format --check src scripts
	uv run --group dev ruff check src scripts

log:
	uv run python scripts/export_log_txt.py

graph:
	uv run python scripts/export_langgraph_mermaid.py

clean:
	rm -rf .ruff_cache
	find . -type d -name '__pycache__' -exec rm -rf {} +
	rm -rf log
