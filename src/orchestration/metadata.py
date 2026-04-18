"""编排层 metadata：预处理阶段生成（M4），记忆检索占位 NO-OP。"""

from __future__ import annotations

import re
from typing import Literal

from langchain_core.messages import BaseMessage

from context.token_budget import count_messages_tokens

from .state import OrchestrationMetadata
from .triage import triage_route_from_text

_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_FILE_EXT_RE = re.compile(
    r"\.(pdf|md|txt|docx?|xlsx?|csv|json|ya?ml|py|rs|ts|js)\b",
    re.IGNORECASE,
)


def _detect_url_or_file(text: str) -> bool:
    t = text or ""
    return bool(_URL_RE.search(t) or _FILE_EXT_RE.search(t))


def build_orchestration_metadata(
    messages: list[BaseMessage],
    user_text: str,
) -> OrchestrationMetadata:
    """由完整会话与本轮用户文本生成 metadata（无 LLM）。"""
    suggested = triage_route_from_text(user_text)
    ask_or_plan: Literal["ask", "plan"] = "plan" if suggested == "complex" else "ask"
    difficulty: Literal["trivial", "simple", "complex"]
    if suggested == "complex":
        difficulty = "complex"
    elif len((user_text or "").strip()) < 12 and ask_or_plan == "ask":
        difficulty = "trivial"
    else:
        difficulty = "simple"

    score = {"trivial": 0, "simple": 1, "complex": 2}[difficulty]

    return {
        "difficulty": difficulty,
        "difficulty_score": score,
        "ask_or_plan": ask_or_plan,
        "detected_url_or_file": _detect_url_or_file(user_text),
        "history_token_estimate": count_messages_tokens(messages),
        "memory_retrieval_enabled": False,
        "suggested_route": suggested,
        "task_text": (user_text or "").strip(),
    }
