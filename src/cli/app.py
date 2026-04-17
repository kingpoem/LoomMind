"""本地终端多轮对话入口（流式输出）。"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from api import create_chat_model
from context import ContentManager

from .response_check import ResponseAction, detect_reply_command

_SYSTEM_PROMPT = "你是简洁助手，用中文回答。"


def run_cli() -> None:
    """本地多轮问答（不连接飞书）。

    用户输入或模型整段回复经去空白、小写后恰好为 exit 或 log 时，
    结束会话或打印当前对话 JSON 并写入 log/raw/。
    """
    model = create_chat_model()
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
                for chunk in model.stream(messages):
                    piece = chunk.content
                    if not piece:
                        continue
                    text = piece if isinstance(piece, str) else str(piece)
                    if text:
                        print(text, end="", flush=True)
                        parts.append(text)
                print()
                assistant_text = "".join(parts)
            except Exception:
                manager.persist(messages)
                raise
            messages.append(AIMessage(content=assistant_text))

            assistant_action = detect_reply_command(assistant_text)
            manager.persist(messages)
            if assistant_action is ResponseAction.EXIT:
                break
            if assistant_action is ResponseAction.LOG:
                print(manager.dumps_session(messages))
    finally:
        manager.persist(messages)
