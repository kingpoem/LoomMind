.PHONY: run clean format lint log graph

run:
	cargo run --manifest-path tui/Cargo.toml

format:
	uv run --group dev ruff format src scripts
	cargo fmt --manifest-path tui/Cargo.toml

lint:
	uv run --group dev ruff format --check src scripts
	uv run --group dev ruff check src scripts

log:
	@uv run python scripts/export_log_txt.py

graph:
	uv run python scripts/export_langgraph_mermaid.py

ifeq ($(OS),Windows_NT)
clean:
	@powershell -NoProfile -Command "if (Test-Path '.ruff_cache') { Remove-Item -Recurse -Force '.ruff_cache' }"
	@powershell -NoProfile -Command "Get-ChildItem -Path . -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"
	@powershell -NoProfile -Command "if (Test-Path 'log') { Get-ChildItem 'log' -Force | Where-Object { $$_.Name -ne '.gitkeep' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue }"
	@powershell -NoProfile -Command "if (Test-Path 'tui\target') { Remove-Item -Recurse -Force 'tui\target' }"
else
clean:
	rm -rf .ruff_cache
	find . -type d -name '__pycache__' -exec rm -rf {} +
	@if [ -d log ]; then find log -mindepth 1 ! -name '.gitkeep' -exec rm -rf {} +; fi
	rm -rf tui/target
endif
