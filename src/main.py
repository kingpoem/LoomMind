"""LoomMind 入口：--lark（默认）连接飞书长连接；--cli 为本地终端问答。"""

from dotenv import load_dotenv

from parser import parse_args


def main() -> None:
    load_dotenv()
    args = parse_args()
    if args.cli:
        from graph_agent import run_local_demo

        run_local_demo()
        return

    from feishu_app import run_feishu_long_connection

    run_feishu_long_connection()


if __name__ == "__main__":
    main()
