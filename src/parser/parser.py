"""CLI 参数解析。
uv run python src/main.py --lark              # 飞书长连接
uv run python src/main.py --cli --stdio       # TUI 子进程（stdin/stdout NDJSON）
本地交互请用：`cargo run --manifest-path tui/Cargo.toml`
"""

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LoomMind：LangGraph + 飞书（用户身份发消息）")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--lark",
        action="store_true",
        help="启动飞书长连接，在飞书中对话",
    )
    mode.add_argument(
        "--cli",
        action="store_true",
        help=("本地模式（须与 --stdio 联用；交互请用 `cargo run --manifest-path tui/Cargo.toml`）"),
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help=("与 --cli 联用：stdin/stdout NDJSON 与 TUI 通信（独占终端时请用 TUI 启动）"),
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)
