"""LoomMind 入口：须指定 --lark 或 --cli。"""

import logging

from dotenv import load_dotenv

from cli import run_cli, run_cli_stdio
from lark import run_feishu_long_connection
from memory import ensure_memory_files
from parser import parse_args
from skills import list_skill_names


def _quiet_http_loggers() -> None:
    """关闭 HTTP 客户端在 INFO 下刷屏（如 httpx 的 POST … 200 OK）。"""
    for name in ("httpx", "httpcore", "openai", "langsmith", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    load_dotenv()
    ensure_memory_files()
    _quiet_http_loggers()
    args = parse_args()

    if args.stdio and not args.cli:
        raise SystemExit("--stdio 须与 --cli 同时使用")

    if args.list_skills:
        names = list_skill_names()
        print(f"Connected skills: {len(names)}")
        for n in names:
            print(f"- {n}")
        return

    if args.lark:
        run_feishu_long_connection()
        return

    if args.cli and args.stdio:
        run_cli_stdio()
        return

    run_cli()


if __name__ == "__main__":
    main()
