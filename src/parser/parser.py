"""CLI 参数解析。
uv run python src/main.py --lark       # 飞书长连接
uv run python src/main.py --cli        # 本地终端多轮对话
uv run python src/main.py --help
"""

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LoomMind：LangGraph + 飞书（用户身份发消息）"
    )

    parser.add_argument(
        "--list-skills",
        action="store_true",
        help="启动前打印已接入的 skills/tools 清单并退出",
    )
    parser.add_argument(
        "--verify-banned",
        metavar="TEXT",
        default=None,
        help="用给定 TEXT 调用 check_banned_words 做一次验证并退出",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--lark",
        action="store_true",
        help="启动飞书长连接，在飞书中对话",
    )
    mode.add_argument(
        "--cli",
        action="store_true",
        help="在本地终端中进行多轮对话（不连接飞书）",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)
