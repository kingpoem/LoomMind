"""战略层扫描：URL/工具名启发式、complex 路径动态 MCP 白名单（M5）。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from graph_agent import list_available_mcps, list_available_skills

# 与 MCP 工具名子串匹配，用于「含 https 时尝试使能 web 类工具」
_WEB_NAME_HINTS: tuple[str, ...] = (
    "web",
    "http",
    "fetch",
    "curl",
    "browse",
    "url",
)

# 占位：未来可注册的真实工具名（单测可 monkeypatch list_available_mcps 命中）
_WEB_TOOL_ALIASES: tuple[str, ...] = (
    "web_fetch",
    "http_get",
    "fetch_url",
    "mcp_web_search",
)


def _is_web_related_tool_name(name: str) -> bool:
    n = name.lower()
    if any(h in n for h in _WEB_NAME_HINTS):
        return True
    return any(alias == name or alias.lower() == n for alias in _WEB_TOOL_ALIASES)


def _has_http_url(text: str) -> bool:
    return bool(re.search(r"https?://", text or "", re.IGNORECASE))


def apply_strategic_layer(
    *,
    task_text: str,
    metadata: dict[str, Any],
    base_mcps: set[str] | None,
    base_skills: set[str] | None,
) -> dict[str, Any]:
    """返回要 merge 进 `OrchestrationState` 的增量字段。

    - `memory_retrieval_enabled` 恒为 False（NO-OP）。
    - 含 `https?://` 且存在名称命中的 MCP：在 **base_mcps 非空** 时做并集注入；
      `base_mcps is None`（会话未限制）时不收窄为仅 web，仅记录 suggestions。
    - 无链接：不写 `complex_enabled_mcps`。
    """
    suggestions: list[str] = []
    complex_mcps: list[str] | None = None

    all_mcps = list(list_available_mcps())
    extras = [n for n in all_mcps if _is_web_related_tool_name(n)]

    if _has_http_url(task_text):
        if extras:
            suggestions.append(f"web_hook:matched_mcps={extras}")
            if base_mcps is not None:
                merged = sorted(set(base_mcps) | set(extras))
                if merged != sorted(base_mcps):
                    complex_mcps = merged
        else:
            suggestions.append(
                "web_hook:no_matching_mcp_in_session "
                f"(aliases={list(_WEB_TOOL_ALIASES)})"
            )
    else:
        suggestions.append("web_hook:skipped_no_http_url")

    _ = list(list_available_skills())  # 占位：后续按 skill 名做动态注入
    if base_skills is not None and not base_skills:
        suggestions.append("skills:empty_allowlist")

    meta = dict(metadata)
    meta["tool_injection_suggestions"] = suggestions
    meta["history_mode"] = "recent_tail_40_complex"
    meta["memory_retrieval_enabled"] = False

    out: dict[str, Any] = {"orchestration_metadata": meta}
    if complex_mcps is not None:
        out["complex_enabled_mcps"] = complex_mcps
    return out


def normalize_allowlist(names: Iterable[str] | None) -> set[str] | None:
    if names is None:
        return None
    return set(names)
