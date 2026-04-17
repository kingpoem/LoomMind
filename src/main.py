"""LoomMind 入口：须指定 --lark 或 --cli。"""

from dotenv import load_dotenv

from cli import run_cli
from lark import run_feishu_long_connection
from parser import parse_args
from skills import load_all_skills


def _print_connected_skills() -> None:
    skills = load_all_skills()
    print(f"Connected skills: {len(skills)}")
    for t in skills:
        print(f"- {getattr(t, 'name', '(unknown)')}")


def _verify_banned_skill(text: str) -> None:
    tools = load_all_skills()
    tool = next((t for t in tools if getattr(t, "name", None) == "check_banned_words"), None)
    if tool is None:
        raise RuntimeError("check_banned_words skill 未加载到（请检查 skills_config.json）")

    # StructuredTool: use invoke with dict input inferred from function signature
    result = tool.invoke({"text": text})
    print("verify-banned input:", text)
    print("verify-banned output:", result)


def main() -> None:
    load_dotenv()
    args = parse_args()
    _print_connected_skills()

    if args.list_skills:
        return
    if args.verify_banned is not None:
        _verify_banned_skill(args.verify_banned)
        return

    if args.lark:
        run_feishu_long_connection()
        return

    run_cli()


if __name__ == "__main__":
    main()
