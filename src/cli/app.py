"""本地终端多轮对话入口（流式输出，支持工具调用）。"""

import subprocess
from pathlib import Path

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from context import ContentManager
from context.compass import compass_compress
from context.token_budget import TOKEN_CONTEXT_LIMIT, count_messages_tokens
from graph_agent import build_graph

from .response_check import ResponseAction, detect_reply_command

_SYSTEM_PROMPT = "你是简洁助手，用中文回答。"


def _run_make_log() -> None:
    root = Path(__file__).resolve().parents[2]
    subprocess.run(["make", "log"], cwd=root, check=False)


def run_cli() -> None:
    """本地多轮问答（不连接飞书），支持工具调用。

    exit 结束；compass 压缩早期会话（摘要写入系统提示）。
    """
    app = build_graph()
    manager = ContentManager()
    messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM_PROMPT)]
    manager.persist(messages)

    print("exit 结束; compass 手动压缩会话")
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
            if user_action is ResponseAction.COMPASS:
                messages, status = compass_compress(messages)
                print(status)
                manager.persist(messages)
                used = count_messages_tokens(messages)
                print(
                    f"[token] 已用 {used:,} / 上限 {TOKEN_CONTEXT_LIMIT:,}",
                    flush=True,
                )
                continue

            prospective = count_messages_tokens(
                [*messages, HumanMessage(content=user_text)]
            )
            if prospective > TOKEN_CONTEXT_LIMIT:
                print(
                    f"本轮输入后约 {prospective:,} token，"
                    f"已超过上限 {TOKEN_CONTEXT_LIMIT:,}，"
                    "请缩短对话或新开会话后再试。"
                )
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
                    if not assistant_text and messages:
                        last = messages[-1]
                        if isinstance(last, AIMessage) and isinstance(
                            last.content, str
                        ):
                            assistant_text = last.content
                            if assistant_text:
                                print(assistant_text)
            except Exception:
                manager.persist(messages)
                raise

            assistant_action = detect_reply_command(assistant_text)
            manager.persist(messages)
            _run_make_log()
            used = count_messages_tokens(messages)
            print(
                f"[token] 已用 {used:,} / 上限 {TOKEN_CONTEXT_LIMIT:,}",
                flush=True,
            )
            if assistant_action is ResponseAction.EXIT:
                break
    finally:
        manager.persist(messages)
