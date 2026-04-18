"""子任务 role → 子图 `build_graph` 白名单（M8）。"""

import os
from typing import Literal

Role = Literal["code", "reasoning", "generic"]

# 与仓库内置 MCP 名对齐（files / run_bash）
_CODE_MCPS: frozenset[str] = frozenset(
    {"read_file", "edit_file", "write_file", "run_bash"}
)
_REASONING_MCPS: frozenset[str] = frozenset({"read_file"})

_ROLE_MODEL_ENV: dict[Role, str] = {
    "code": "LOOMMIND_MODEL_ROLE_CODE",
    "reasoning": "LOOMMIND_MODEL_ROLE_REASONING",
    "generic": "LOOMMIND_MODEL_ROLE_GENERIC",
}


def normalize_role(raw: str | None) -> Role:
    r = (raw or "generic").strip().lower()
    if r in ("code", "reasoning", "generic"):
        return r  # type: ignore[return-value]
    return "generic"


def merged_mcp_names(
    *,
    universe: list[str],
    session_mcps: list[str] | None,
    strategic_mcps: list[str] | None,
) -> list[str]:
    """会话 + 战略层后的有效 MCP 全集（显式列表）。"""
    if strategic_mcps is not None:
        return sorted(set(str(x) for x in strategic_mcps))
    if session_mcps is not None:
        return sorted(set(str(x) for x in session_mcps))
    return sorted(set(universe))


def merged_skill_names(
    *,
    universe: list[str],
    session_skills: list[str] | None,
    strategic_skills: list[str] | None,
) -> list[str]:
    if strategic_skills is not None:
        return sorted(set(str(x) for x in strategic_skills))
    if session_skills is not None:
        return sorted(set(str(x) for x in session_skills))
    return sorted(set(universe))


def allowlists_for_role(
    role: Role,
    *,
    merged_mcps: list[str],
    merged_skills: list[str],
) -> tuple[list[str], list[str]]:
    """返回 (enabled_mcps, enabled_skills)。若 role 收窄后为空则退回 generic（全 merged）。"""
    if role == "generic":
        return list(merged_mcps), list(merged_skills)

    if role == "code":
        mcps = [n for n in merged_mcps if n in _CODE_MCPS]
        skills = [n for n in merged_skills if "code" in n.lower()]
        if not mcps and not skills:
            return list(merged_mcps), list(merged_skills)
        if not mcps:
            return list(merged_mcps), skills or list(merged_skills)
        return mcps, skills or list(merged_skills)

    # reasoning
    mcps = [n for n in merged_mcps if n in _REASONING_MCPS]
    skills = [n for n in merged_skills if "reason" in n.lower() or "logic" in n.lower()]
    if not mcps and not skills:
        return list(merged_mcps), list(merged_skills)
    if not mcps:
        return list(merged_mcps), skills or list(merged_skills)
    return mcps, skills or list(merged_skills)


def model_name_for_role(role: Role, default: str | None) -> str | None:
    key = _ROLE_MODEL_ENV.get(role)
    if not key:
        return default
    raw = os.environ.get(key, "").strip()
    return raw or default
