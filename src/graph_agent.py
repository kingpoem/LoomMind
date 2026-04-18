"""LangGraph Agent：接入 planning 循环与工具调用。"""

from collections.abc import Iterable

from langchain_core.tools import BaseTool

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
    )
