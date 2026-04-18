"""LangGraph Agent：接入 planning 循环与工具调用。"""

import os
from collections.abc import Iterable
from typing import Literal

from langchain_core.tools import BaseTool

from api.runtime_settings import LLMRuntimeSettings
from planning import build_planning_graph, resolve_planning_max_cycles
from skills import load_all_skills
from tools.loader import load_tools


def list_available_skills() -> list[str]:
    return [str(getattr(t, "name", "")) for t in load_all_skills()]


def list_available_mcps() -> list[str]:
    return [str(getattr(t, "name", "")) for t in load_tools()]


def _filter_tools(
    tools: list[BaseTool], allowed: Iterable[str] | None
) -> list[BaseTool]:
    if allowed is None:
        return list(tools)
    allow = set(allowed)
    return [t for t in tools if str(getattr(t, "name", "")) in allow]


def build_graph(
    *,
    model_name: str | None = None,
    enabled_skills: Iterable[str] | None = None,
    enabled_mcps: Iterable[str] | None = None,
    max_cycles: int | None = None,
    llm_settings: LLMRuntimeSettings | None = None,
):
    """构建 LangGraph。

    - `model_name=None` 走默认模型；
    - `enabled_skills=None` 表示「全部启用」，传空集合即「全部禁用」；
    - `enabled_mcps` 同上；
    - `max_cycles=None` 时使用环境变量 `LOOMMIND_MAX_PLAN_CYCLES`（若未设置则为 6），
      显式传入则覆盖环境变量。
    """
    mcps = _filter_tools(load_tools(), enabled_mcps)
    skills = _filter_tools(load_all_skills(), enabled_skills)
    tools: list[BaseTool] = [*mcps, *skills]
    return build_planning_graph(
        model_name=model_name,
        tools=tools,
        max_cycles=resolve_planning_max_cycles(max_cycles),
        llm_settings=llm_settings,
    )


def session_graph_entry_mode() -> Literal["orchestration", "legacy"]:
    """与 `build_session_graph` 一致：当前进程将使用的入口图类型（供 CLI/stdio/飞书展示）。"""
    from orchestration.config import use_legacy_planning_graph

    return "legacy" if use_legacy_planning_graph() else "orchestration"


def _max_review_reject_retries() -> int:
    raw = os.environ.get("LOOMMIND_MAX_REVIEW_REJECT_RETRIES", "").strip()
    if not raw:
        return 2
    try:
        return max(0, int(raw))
    except ValueError:
        return 2


def build_session_graph(
    *,
    model_name: str | None = None,
    enabled_skills: Iterable[str] | None = None,
    enabled_mcps: Iterable[str] | None = None,
    max_cycles: int | None = None,
):
    """CLI / stdio / 飞书入口使用的图：默认走编排层，旧版单图见环境变量说明。

    `LOOMMIND_ORCHESTRATION=legacy`（等）时使用 `build_graph()`；
    否则使用 `orchestration.build_orchestration_graph()`。
    """
    from orchestration import build_orchestration_graph, use_legacy_planning_graph

    if use_legacy_planning_graph():
        return build_graph(
            model_name=model_name,
            enabled_skills=enabled_skills,
            enabled_mcps=enabled_mcps,
            max_cycles=max_cycles,
        )
    return build_orchestration_graph(
        model_name=model_name,
        enabled_skills=enabled_skills,
        enabled_mcps=enabled_mcps,
        max_cycles=max_cycles,
        max_review_reject_retries=_max_review_reject_retries(),
    )
