"""LoomMind 入口：须指定 --lark 或 --cli。"""

from dotenv import load_dotenv

from parser import parse_args


def main() -> None:
    load_dotenv()
    args = parse_args()
    if args.lark:
        from feishu_app import run_feishu_long_connection

        run_feishu_long_connection()
        return

    from graph_agent import run_local_demo

    run_local_demo()


if __name__ == "__main__":
    main()
