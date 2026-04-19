"""LoomMind 入口：须指定 --lark 或 --cli（--stdio，供 TUI 子进程使用）。"""

import logging

from cli import run_cli_stdio
from lark import run_feishu_long_connection
from memory import ensure_memory_files
from parser import parse_args
from settings import ensure_settings_file


def _quiet_http_loggers() -> None:
    """关闭 HTTP 客户端在 INFO 下刷屏（如 httpx 的 POST … 200 OK）。"""
    for name in ("httpx", "httpcore", "openai", "langsmith", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    ensure_settings_file()
    ensure_memory_files()
    _quiet_http_loggers()
    args = parse_args()

    if args.stdio and not args.cli:
        raise SystemExit("--stdio 须与 --cli 同时使用")

    if args.lark:
        run_feishu_long_connection()
        return

    if not args.stdio:
        raise SystemExit("本地对话请使用 TUI：在项目根执行 `cargo run --manifest-path tui/Cargo.toml`（或 `make run`）")

    run_cli_stdio()


if __name__ == "__main__":
    main()
