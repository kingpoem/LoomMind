"""本地终端多轮对话入口"""

import json
import subprocess
import sys
import traceback
from collections.abc import Iterable
from pathlib import Path

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

import trust
from api import default_model_name, list_available_models
from context import ContentManager
from context.compass import compass_compress
from context.token_budget import TOKEN_CONTEXT_LIMIT, count_messages_tokens
from graph_agent import build_graph, list_available_mcps, list_available_skills
from memory import build_system_prompt_with_memory, record_compass_digest
from tools.loader import set_confirmation_callback, set_notification_callback

from .response_check import ResponseAction, detect_reply_command
from .stdio_confirm import stdio_tool_confirm, stdio_tool_notify
from .stdio_protocol import emit, read_command_line
from .stdio_trust import stdio_trust_prompt

_CORE_SYSTEM_PROMPT = "你是简洁助手，用中文回答。回答格式扁平化，段落化"


def _run_make_log(*, silence: bool = False) -> None:
    """导出会话 log。

    `silence=True` 时子进程不写 stdout/stderr（stdio 模式 stdout 仅能为 NDJSON）。
    """
    root = Path(__file__).resolve().parents[2]
    if silence:
        subprocess.run(
            ["make", "log"],
            cwd=root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.run(["make", "log"], cwd=root, check=False)


def _tty_trust_prompt(workspace: Path) -> bool:
    """CLI 启动时询问工作区信任；非 tty 一律按不信任处理。"""
    if not sys.stdin.isatty():
        return False
    print(f"是否信任 AI 访问当前工作区 {workspace}？")
    ans = input("这将允许AI读取该目录下的文件。[y/N] ").strip().lower()
    return ans in ("y", "yes")


def run_cli() -> None:
    """本地多轮问答（不连接飞书），支持工具调用。

    /exit、/quit 结束；/compass 压缩早期会话（摘要写入系统提示）。
    """
    trust.prompt_for_trust(_tty_trust_prompt)
    app = build_graph()
    manager = ContentManager()
    messages: list[BaseMessage] = [
        SystemMessage(content=build_system_prompt_with_memory(_CORE_SYSTEM_PROMPT)),
    ]
    manager.persist(messages)

    print("/exit、/quit 结束; /compass 手动压缩会话")
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
                messages, status, digest = compass_compress(messages)
                print(status)
                if digest:
                    record_compass_digest(digest)
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


# ---------------------------------------------------------------------------
# stdio (TUI) entry
# ---------------------------------------------------------------------------


class _Session:
    """会话级配置：模型 / 启用的 skills / 启用的 mcps。

    `enabled_skills`/`enabled_mcps` 为 `None` 时表示「全部启用」。
    """

    def __init__(self) -> None:
        self.model_name: str = default_model_name()
        self.available_models: list[str] = list_available_models()
        self.available_skills: list[str] = list_available_skills()
        self.available_mcps: list[str] = list_available_mcps()
        # 默认启用全部
        self.enabled_skills: set[str] = set(self.available_skills)
        self.enabled_mcps: set[str] = set(self.available_mcps)
        self.graph = self._build()

    def _build(self):
        return build_graph(
            model_name=self.model_name,
            enabled_skills=sorted(self.enabled_skills),
            enabled_mcps=sorted(self.enabled_mcps),
        )

    def set_model(self, name: str) -> str:
        if name not in self.available_models:
            raise ValueError(f"未知模型：{name}")
        self.model_name = name
        self.graph = self._build()
        return name

    def set_skills(self, names: Iterable[str]) -> list[str]:
        wanted = set(names)
        unknown = wanted - set(self.available_skills)
        if unknown:
            raise ValueError(f"未知 skill：{sorted(unknown)}")
        self.enabled_skills = wanted
        self.graph = self._build()
        return sorted(self.enabled_skills)

    def set_mcps(self, names: Iterable[str]) -> list[str]:
        wanted = set(names)
        unknown = wanted - set(self.available_mcps)
        if unknown:
            raise ValueError(f"未知 mcp：{sorted(unknown)}")
        self.enabled_mcps = wanted
        self.graph = self._build()
        return sorted(self.enabled_mcps)


def _emit_models(session: _Session) -> None:
    emit(
        {
            "type": "models",
            "items": session.available_models,
            "current": session.model_name,
        }
    )


def _emit_skills(session: _Session) -> None:
    emit(
        {
            "type": "skills",
            "items": session.available_skills,
            "selected": sorted(session.enabled_skills),
        }
    )


def _emit_mcps(session: _Session) -> None:
    emit(
        {
            "type": "mcps",
            "items": session.available_mcps,
            "selected": sorted(session.enabled_mcps),
        }
    )


def run_cli_stdio() -> None:
    """与 `run_cli` 相同业务逻辑，经 stdin/stdout NDJSON 与 TUI 通信。"""
    set_confirmation_callback(stdio_tool_confirm)
    set_notification_callback(stdio_tool_notify)
    # 信任询问先于 ready：TUI 在收到 ready 前用 overlay 阻塞输入。
    trust.prompt_for_trust(stdio_trust_prompt)
    session = _Session()
    manager = ContentManager()
    messages: list[BaseMessage] = [
        SystemMessage(content=build_system_prompt_with_memory(_CORE_SYSTEM_PROMPT)),
    ]
    manager.persist(messages)

    emit(
        {
            "type": "ready",
            "message": "已就绪",
            "model": session.model_name,
        }
    )
    try:
        while True:
            try:
                raw = read_command_line()
            except json.JSONDecodeError as e:
                emit({"type": "error", "message": f"无效 JSON: {e}"})
                continue
            if raw is None:
                emit({"type": "session_end", "reason": "eof"})
                break
            if not raw:
                continue

            cmd_type = raw.get("type")

            # --- 控制类指令 -------------------------------------------------
            if cmd_type in ("shutdown", "quit", "exit"):
                emit({"type": "session_end", "reason": cmd_type})
                break

            if cmd_type == "list_models":
                _emit_models(session)
                continue
            if cmd_type == "set_model":
                try:
                    name = session.set_model(str(raw.get("name", "")))
                except ValueError as e:
                    emit({"type": "error", "message": str(e)})
                else:
                    emit({"type": "model_set", "name": name})
                continue

            if cmd_type == "list_skills":
                _emit_skills(session)
                continue
            if cmd_type == "set_skills":
                names = raw.get("names") or []
                try:
                    selected = session.set_skills(names)
                except ValueError as e:
                    emit({"type": "error", "message": str(e)})
                else:
                    emit({"type": "skills_set", "selected": selected})
                continue

            if cmd_type == "list_mcps":
                _emit_mcps(session)
                continue
            if cmd_type == "set_mcps":
                names = raw.get("names") or []
                try:
                    selected = session.set_mcps(names)
                except ValueError as e:
                    emit({"type": "error", "message": str(e)})
                else:
                    emit({"type": "mcps_set", "selected": selected})
                continue

            if cmd_type != "user_message":
                emit({"type": "error", "message": f"未知指令类型: {cmd_type!r}"})
                continue

            user_text = (raw.get("text") or "").strip()
            if not user_text:
                continue

            user_action = detect_reply_command(user_text)
            if user_action is ResponseAction.EXIT:
                emit({"type": "session_end", "reason": "user_exit"})
                break
            if user_action is ResponseAction.COMPASS:
                messages, status, digest = compass_compress(messages)
                emit({"type": "system", "message": status})
                if digest:
                    record_compass_digest(digest)
                manager.persist(messages)
                used = count_messages_tokens(messages)
                emit(
                    {
                        "type": "token_usage",
                        "used": used,
                        "limit": TOKEN_CONTEXT_LIMIT,
                    }
                )
                continue

            prospective = count_messages_tokens(
                [*messages, HumanMessage(content=user_text)]
            )
            if prospective > TOKEN_CONTEXT_LIMIT:
                emit(
                    {
                        "type": "system",
                        "message": (
                            f"本轮输入后约 {prospective:,} token，"
                            f"已超过上限 {TOKEN_CONTEXT_LIMIT:,}，"
                            "请缩短对话或新开会话后再试。"
                        ),
                    }
                )
                continue

            messages.append(HumanMessage(content=user_text))
            try:
                parts: list[str] = []
                final_state: dict | None = None
                for mode, data in session.graph.stream(
                    {"messages": messages},
                    stream_mode=["messages", "values"],
                ):
                    if mode == "messages":
                        chunk, _ = data
                        if isinstance(chunk, AIMessageChunk) and isinstance(
                            chunk.content, str
                        ):
                            if chunk.content:
                                emit({"type": "assistant_delta", "text": chunk.content})
                                parts.append(chunk.content)
                    elif mode == "values":
                        final_state = data

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
                                emit(
                                    {
                                        "type": "assistant_message",
                                        "text": assistant_text,
                                    }
                                )
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                emit({"type": "error", "message": str(e)})
                manager.persist(messages)
                continue

            assistant_action = detect_reply_command(assistant_text)
            manager.persist(messages)
            _run_make_log(silence=True)
            used = count_messages_tokens(messages)
            emit({"type": "token_usage", "used": used, "limit": TOKEN_CONTEXT_LIMIT})
            if assistant_action is ResponseAction.EXIT:
                emit({"type": "session_end", "reason": "assistant_exit"})
                break
    finally:
        manager.persist(messages)
