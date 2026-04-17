"""LoomMind 入口：须指定 --lark 或 --cli。"""

from dotenv import load_dotenv

from cli import run_cli
from lark import run_feishu_long_connection
from parser import parse_args
from skills import list_skill_names

def main() -> None:
    load_dotenv()
    args = parse_args()

    if args.list_skills:
        names = list_skill_names()
        print(f"Connected skills: {len(names)}")
        for n in names:
            print(f"- {n}")
        return

    if args.lark:
        run_feishu_long_connection()
        return

    run_cli()


if __name__ == "__main__":
    main()
