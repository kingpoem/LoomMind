"""TUI 子进程：stdio NDJSON 多轮对话。"""

import json
import subprocess
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
from api.ollama import normalized_openai_api_base
from api.provider import LLMProvider
from api.runtime_settings import LLMRuntimeSettings
from context import ContentManager
from context.compass import compass_compress
from context.token_budget import (
    count_messages_tokens,
    token_auto_compress_max_rounds,
    token_auto_compress_ratio,
    token_context_limit,
)
from graph_agent import build_graph, list_available_mcps, list_available_skills
from memory import build_system_prompt_with_memory, record_compass_digest
from planning import resolve_planning_max_cycles
from prompt_text import load_template_prompt
from settings import get_str, merge_llm_provider, merge_wire_llm_key
from tools.loader import set_confirmation_callback, set_notification_callback
from user_input_parse import UserInputSymbolTable, build_user_input_symbol_table

from .post_model_config import collect_post_model_config_items
from .stdio_confirm import stdio_tool_confirm, stdio_tool_notify
from .stdio_protocol import emit, read_command_line
from .stdio_trust import stdio_trust_prompt

_CORE_SYSTEM_PROMPT = load_template_prompt("core/system.txt")


def _auto_compress_if_over_threshold(
    messages: list[BaseMessage],
    *,
    pending_user: HumanMessage,
    llm: LLMRuntimeSettings,
    manager: ContentManager,
) -> tuple[list[BaseMessage], bool]:
    ratio = token_auto_compress_ratio()
    if ratio <= 0:
        return messages, False
    limit = token_context_limit()
    threshold = max(1, int(limit * ratio))
    did_any = False
    for _ in range(token_auto_compress_max_rounds()):
        prospective = count_messages_tokens([*messages, pending_user])
        if prospective <= threshold:
            break
        before = count_messages_tokens(messages)
        messages, _status, digest = compass_compress(messages, llm=llm)
        after = count_messages_tokens(messages)
        if digest:
            record_compass_digest(digest)
        if after >= before:
            break
        did_any = True
        manager.persist(messages)
    return messages, did_any


def _run_make_log(*, silence: bool = False) -> None:
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


# ---------------------------------------------------------------------------
# stdio（TUI 子进程）
# ---------------------------------------------------------------------------


class _Session:
    def __init__(self) -> None:
        self.llm = LLMRuntimeSettings()
        self.model_name: str = default_model_name(llm=self.llm)
        self.available_models: list[str] = list_available_models(llm=self.llm)
        self.available_skills: list[str] = list_available_skills()
        self.available_mcps: list[str] = list_available_mcps()
        # 默认启用全部
        self.enabled_skills: set[str] = set(self.available_skills)
        self.enabled_mcps: set[str] = set(self.available_mcps)
        self.max_plan_cycles: int | None = None
        self.last_user_input_symbols: UserInputSymbolTable | None = None
        self.graph = self._build()

    def _build(self):
        return build_graph(
            model_name=self.model_name,
            enabled_skills=sorted(self.enabled_skills),
            enabled_mcps=sorted(self.enabled_mcps),
            max_cycles=self.max_plan_cycles,
            llm_settings=self.llm,
        )

    def clear_llm_override_for_env_key(self, key: str) -> None:
        if key == "OPENROUTER_API_KEY":
            self.llm.openrouter_api_key = None
        elif key == "OLLAMA_BASE_URL":
            self.llm.ollama_base_url = None
        elif key == "OLLAMA_API_KEY":
            self.llm.ollama_api_key = None

    def apply_llm_config(self, raw: dict) -> None:
        if raw.get("clear") is True:
            self.llm = LLMRuntimeSettings()
        else:
            if "provider" in raw:
                v = raw["provider"]
                if v is None or (isinstance(v, str) and not str(v).strip()):
                    self.llm.provider = None
                else:
                    p = str(v).strip().lower()
                    if p == LLMProvider.OLLAMA:
                        self.llm.provider = LLMProvider.OLLAMA
                    elif p == LLMProvider.OPENROUTER:
                        self.llm.provider = LLMProvider.OPENROUTER
                    else:
                        raise ValueError(p)
            for json_key, attr in (
                ("openrouter_api_key", "openrouter_api_key"),
                ("ollama_api_key", "ollama_api_key"),
                ("ollama_base_url", "ollama_base_url"),
            ):
                if json_key not in raw:
                    continue
                val = raw[json_key]
                if val is None:
                    setattr(self.llm, attr, None)
                else:
                    st = str(val).strip()
                    setattr(self.llm, attr, st or None)
        self.available_models = list_available_models(llm=self.llm)
        if self.model_name not in self.available_models:
            self.model_name = default_model_name(llm=self.llm)
        self.graph = self._build()

    def set_model(self, name: str) -> str:
        if name not in self.available_models:
            raise ValueError(name)
        self.model_name = name
        self.graph = self._build()
        return name

    def set_skills(self, names: Iterable[str]) -> list[str]:
        wanted = set(names)
        unknown = wanted - set(self.available_skills)
        if unknown:
            raise ValueError(str(sorted(unknown)))
        self.enabled_skills = wanted
        self.graph = self._build()
        return sorted(self.enabled_skills)

    def set_mcps(self, names: Iterable[str]) -> list[str]:
        wanted = set(names)
        unknown = wanted - set(self.available_mcps)
        if unknown:
            raise ValueError(str(sorted(unknown)))
        self.enabled_mcps = wanted
        self.graph = self._build()
        return sorted(self.enabled_mcps)

    def set_max_plan_cycles(self, n: int | None) -> int:
        if n is not None and n < 1:
            raise ValueError(str(n))
        self.max_plan_cycles = n
        self.graph = self._build()
        return resolve_planning_max_cycles(n)


def _emit_models(session: _Session) -> None:
    # Ollama：TUI 侧先展示空列表（由用户配置 base 后再用 /model 拉取）
    if session.llm.effective_provider() is LLMProvider.OLLAMA:
        items: list[str] = []
    else:
        items = session.available_models
    emit(
        {
            "type": "models",
            "items": items,
            "current": session.model_name,
        }
    )


def _emit_providers(session: _Session) -> None:
    emit(
        {
            "type": "providers",
            "items": [LLMProvider.OPENROUTER, LLMProvider.OLLAMA],
            "current": session.llm.effective_provider().value,
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


_PERSISTABLE_ENV_KEYS = frozenset(
    {"OPENROUTER_API_KEY", "OLLAMA_BASE_URL", "OLLAMA_API_KEY"}
)


def _emit_llm_config(session: _Session) -> None:
    s = session.llm
    p = s.effective_provider()
    ork = (
        s.openrouter_api_key.strip()
        if s.openrouter_api_key and str(s.openrouter_api_key).strip()
        else get_str("llm.openrouter.api_key").strip()
    )
    base = normalized_openai_api_base(base_url_override=s.ollama_base_url)
    emit(
        {
            "type": "llm_config",
            "provider": p.value,
            "openrouter_key_set": bool(ork),
            "openrouter_from_session": bool(
                s.openrouter_api_key and str(s.openrouter_api_key).strip()
            ),
            "ollama_base": base,
            "ollama_base_from_session": bool(
                s.ollama_base_url and str(s.ollama_base_url).strip()
            ),
            "ollama_key_from_session": bool(
                s.ollama_api_key and str(s.ollama_api_key).strip()
            ),
            "provider_from_session": s.provider is not None,
            "model": session.model_name,
        }
    )


def run_cli_stdio() -> None:
    set_confirmation_callback(stdio_tool_confirm)
    set_notification_callback(stdio_tool_notify)
    trust.ensure_trust_at_startup(stdio_trust_prompt)
    session = _Session()
    manager = ContentManager()
    messages: list[BaseMessage] = [
        SystemMessage(content=build_system_prompt_with_memory(_CORE_SYSTEM_PROMPT)),
    ]
    manager.persist(messages)

    emit(
        {
            "type": "ready",
            "message": "就绪",
            "model": session.model_name,
            "llm_provider": session.llm.effective_provider().value,
            "max_plan_cycles": resolve_planning_max_cycles(session.max_plan_cycles),
        }
    )
    try:
        while True:
            try:
                raw = read_command_line()
            except json.JSONDecodeError as e:
                emit({"type": "error", "message": str(e)})
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

            if cmd_type == "compass":
                messages, status, digest = compass_compress(messages, llm=session.llm)
                emit({"type": "system", "message": status})
                if digest:
                    record_compass_digest(digest)
                manager.persist(messages)
                used = count_messages_tokens(messages)
                emit(
                    {
                        "type": "token_usage",
                        "used": used,
                        "limit": token_context_limit(),
                    }
                )
                continue

            if cmd_type == "list_models":
                _emit_models(session)
                continue
            if cmd_type == "list_providers":
                _emit_providers(session)
                continue
            if cmd_type == "set_provider":
                name = str(raw.get("name", "")).strip().lower()
                if name not in (LLMProvider.OPENROUTER, LLMProvider.OLLAMA):
                    emit(
                        {
                            "type": "error",
                            "message": "provider 须为 openrouter 或 ollama",
                        }
                    )
                    continue
                try:
                    merge_llm_provider(name)
                except ValueError as e:
                    emit({"type": "error", "message": str(e)})
                    continue
                session.llm = LLMRuntimeSettings()
                session.available_models = list_available_models(llm=session.llm)
                session.model_name = default_model_name(llm=session.llm)
                session.graph = session._build()
                _emit_llm_config(session)
                continue
            if cmd_type == "set_model":
                try:
                    name = session.set_model(str(raw.get("name", "")))
                except ValueError as e:
                    emit({"type": "error", "message": str(e)})
                else:
                    items = collect_post_model_config_items(session)
                    payload: dict = {"type": "model_set", "name": name}
                    if items:
                        payload["post_config"] = {"items": items}
                    emit(payload)
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

            if cmd_type == "set_plan_cycles":
                raw_n = raw.get("max_cycles")
                try:
                    if raw_n is None:
                        n = session.set_max_plan_cycles(None)
                    else:
                        n = session.set_max_plan_cycles(int(raw_n))
                except (TypeError, ValueError) as e:
                    emit({"type": "error", "message": f"无效 max_cycles: {e}"})
                else:
                    emit({"type": "plan_cycles_set", "max_plan_cycles": n})
                continue

            if cmd_type == "set_env_persist":
                if not isinstance(raw, dict):
                    emit({"type": "error", "message": "set_env_persist 须为对象"})
                    continue
                key = str(raw.get("key", "")).strip()
                if key not in _PERSISTABLE_ENV_KEYS:
                    emit({"type": "error", "message": key})
                    continue
                val_raw = raw.get("value")
                val_s = "" if val_raw is None else str(val_raw)
                try:
                    if not val_s.strip():
                        merge_wire_llm_key(key, None)
                    else:
                        merge_wire_llm_key(key, val_s.strip())
                    session.clear_llm_override_for_env_key(key)
                    session.available_models = list_available_models(llm=session.llm)
                    if session.model_name not in session.available_models:
                        session.model_name = default_model_name(llm=session.llm)
                    session.graph = session._build()
                except (OSError, ValueError) as e:
                    emit({"type": "error", "message": str(e)})
                else:
                    remaining = collect_post_model_config_items(session)
                    emit(
                        {
                            "type": "env_persisted",
                            "key": key,
                            "post_config": {"items": remaining},
                        }
                    )
                continue

            if cmd_type == "get_llm_config":
                _emit_llm_config(session)
                continue
            if cmd_type == "set_llm_config":
                if not isinstance(raw, dict):
                    emit({"type": "error", "message": "set_llm_config 须为对象"})
                    continue
                try:
                    session.apply_llm_config(raw)
                except ValueError as e:
                    emit({"type": "error", "message": str(e)})
                else:
                    emit({"type": "llm_config_set", "message": "ok"})
                    _emit_llm_config(session)
                continue

            if cmd_type != "user_message":
                emit({"type": "error", "message": str(cmd_type)})
                continue

            user_text = (raw.get("text") or "").strip()
            if not user_text:
                continue

            session.last_user_input_symbols = build_user_input_symbol_table(user_text)
            pending = HumanMessage(content=user_text)
            messages, auto_compressed = _auto_compress_if_over_threshold(
                messages,
                pending_user=pending,
                llm=session.llm,
                manager=manager,
            )
            if auto_compressed:
                pct = round(token_auto_compress_ratio() * 100)
                emit(
                    {
                        "type": "system",
                        "message": f"上下文超过 {pct}% 阈值，已压缩",
                    }
                )
                used = count_messages_tokens(messages)
                emit(
                    {
                        "type": "token_usage",
                        "used": used,
                        "limit": token_context_limit(),
                    }
                )

            prospective = count_messages_tokens([*messages, pending])
            if prospective > token_context_limit():
                lim = token_context_limit()
                emit(
                    {
                        "type": "system",
                        "message": f"约 {prospective:,} token，超过上限 {lim:,}",
                    }
                )
                continue

            messages.append(pending)
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
                emit({"type": "error", "message": str(e)})
                manager.persist(messages)
                continue

            manager.persist(messages)
            _run_make_log(silence=True)
            used = count_messages_tokens(messages)
            emit({"type": "token_usage", "used": used, "limit": token_context_limit()})
    finally:
        manager.persist(messages)
