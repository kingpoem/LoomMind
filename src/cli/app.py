"""本地终端多轮对话入口（流式输出，支持工具调用）。"""

from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from context import ContentManager
from graph_agent import build_graph

from .response_check import ResponseAction, detect_reply_command

_SYSTEM_PROMPT = "你是简洁助手，用中文回答。"


def run_cli() -> None:
    """本地多轮问答（不连接飞书），支持工具调用。

    用户输入或模型整段回复经去空白、小写后恰好为 exit 或 log 时，
    结束会话或打印当前对话 JSON 并写入 log/raw/。
    """
    app = build_graph()
    manager = ContentManager()
    messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM_PROMPT)]
    manager.persist(messages)

    print(
        "多轮问答。输入 exit 结束；输入 log 打印当前全部对话 JSON（并写入 log/raw/）。"
    )
    try:
        while True:
            try:
                user_text = input("你: ").strip()
            except EOFError:
                break
            if not user_text:
                continue

            user_action = detect_reply_command(user_text)
            if user_action is ResponseAction.EXIT:
                break
            if user_action is ResponseAction.LOG:
                print(manager.dumps_session(messages))
                manager.persist(messages)
                continue

            messages.append(HumanMessage(content=user_text))
            try:
                print("助手: ", end="", flush=True)
                parts: list[str] = []
                final_state: dict | None = None
                for mode, data in app.stream(
                    {"messages": messages},
                    stream_mode=["messages", "values"],
                ):
                    if mode == "messages":
                        chunk, _ = data
                        if isinstance(chunk, AIMessageChunk) and isinstance(
                            chunk.content, str
                        ):
                            if chunk.content:
                                print(chunk.content, end="", flush=True)
                                parts.append(chunk.content)
                    elif mode == "values":
                        final_state = data
                print()
                assistant_text = "".join(parts)
                if final_state is not None:
                    messages = list(final_state["messages"])
            except Exception:
                manager.persist(messages)
                raise

            assistant_action = detect_reply_command(assistant_text)
            manager.persist(messages)
            if assistant_action is ResponseAction.EXIT:
                break
            if assistant_action is ResponseAction.LOG:
                print(manager.dumps_session(messages))
    finally:
        manager.persist(messages)
