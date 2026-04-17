"""LoomMind 入口：须指定 --lark 或 --cli。"""

from dotenv import load_dotenv

from cli import run_cli
from lark import run_feishu_long_connection
from parser import parse_args
from skills import list_skill_names


# 全局开关：是否在启动时打印 skills 名单（对 --cli/--lark 都生效）
SHOW_SKILLS_ON_STARTUP = True


def main() -> None:
    load_dotenv()
    args = parse_args()

    if SHOW_SKILLS_ON_STARTUP:
        names = list_skill_names()
        print(f"Connected skills: {len(names)}")
        for n in names:
            print(f"- {n}")

    if args.lark:
        run_feishu_long_connection()
        return

    run_cli()


if __name__ == "__main__":
    main()
