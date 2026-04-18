"""模块主管：分解 → 子图顺序执行 → 聚合（M7/M8）。"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from api import create_chat_model
from graph_agent import build_graph, list_available_mcps, list_available_skills

from .review import last_assistant_draft
from .subtask import DecomposeOutput, SubTaskItem, ensure_min_subtasks
from .worker_profile import (
    allowlists_for_role,
    merged_mcp_names,
    merged_skill_names,
    model_name_for_role,
    normalize_role,
)

_LOG = logging.getLogger(__name__)

_WORKER_SYSTEM = (
    "你是 LoomMind 子任务执行器，在隔离上下文中完成指定子任务。"
    "可调用已注册工具；输出务求简洁，用中文。"
)

_DECOMPOSE_SYSTEM = """你是任务分解器。用户给出一个需要多步完成的总目标。
请输出有序子任务列表（2～6 条）：每条包含 id、title、description、role；
role 只能是字符串 code / reasoning / generic：
- code：需要读改文件或跑命令时使用；
- reasoning：仅需阅读材料与推理、尽量少的工具面；
- generic：与会话默认工具策略一致。
description 必须自洽，执行器**不会**看到完整会话历史，只能看到本子任务描述与总目标摘要。
不要输出 markdown 围栏以外的文字。"""


def run_decompose(*, model_name: str | None, user_goal: str) -> tuple[list[dict[str, Any]], str]:
    """LLM 结构化分解；返回 (subtasks 字典列表, user_goal 回显)。"""
    llm = create_chat_model(model_name)
    structured = llm.with_structured_output(DecomposeOutput)
    try:
        raw = structured.invoke(
            [
                SystemMessage(content=_DECOMPOSE_SYSTEM),
                HumanMessage(
                    content=json.dumps({"user_goal": user_goal}, ensure_ascii=False)
                ),
            ]
        )
        if not isinstance(raw, DecomposeOutput):
            raise TypeError(type(raw))
        items = ensure_min_subtasks(list(raw.subtasks), min_n=2)
    except Exception:
        _LOG.exception("decompose 结构化失败，使用启发式双子任务")
        items = ensure_min_subtasks(
            [
                SubTaskItem(
                    id="1",
                    title="理解与规划",
                    description=f"理解用户目标并列出关键检查点：{user_goal[:400]}",
                    role="code",
                )
            ],
            min_n=2,
        )
    dumped = [s.model_dump() for s in items]
    _LOG.info("module_supervisor decompose count=%s", len(dumped))
    return dumped, user_goal


def _subtask_messages(*, goal: str, row: dict[str, Any]) -> list:
    sid = str(row.get("id", ""))
    title = str(row.get("title", ""))
    desc = str(row.get("description", ""))
    extra = str(row.get("context_data", ""))
    role = normalize_role(str(row.get("role") or row.get("agent_profile") or ""))
    body = f"总目标：\n{goal}\n\n子任务 [{sid}] {title}（role={role}）\n{desc}\n"
    if extra.strip():
        body += f"\n补充材料：\n{extra.strip()}\n"
    return [SystemMessage(content=_WORKER_SYSTEM), HumanMessage(content=body)]


def run_execute_workers(
    *,
    model_name: str | None,
    enabled_skills,
    enabled_mcps,
    complex_enabled_mcps: list[str] | None,
    complex_enabled_skills: list[str] | None,
    subtask_max_cycles: int,
    goal: str,
    subtasks: list[dict[str, Any]],
) -> list[str]:
    """顺序 invoke 子图；每子任务按 role 独立 `build_graph`（工具白名单可不同）。"""
    summaries: list[str] = []
    universe_m = list(list_available_mcps())
    universe_s = list(list_available_skills())
    session_m = sorted(enabled_mcps) if enabled_mcps is not None else None
    session_s = sorted(enabled_skills) if enabled_skills is not None else None
    merged_m = merged_mcp_names(
        universe=universe_m,
        session_mcps=session_m,
        strategic_mcps=complex_enabled_mcps,
    )
    merged_s = merged_skill_names(
        universe=universe_s,
        session_skills=session_s,
        strategic_skills=complex_enabled_skills,
    )

    for row in subtasks:
        role = normalize_role(str(row.get("role") or row.get("agent_profile") or ""))
        mcps, skills = allowlists_for_role(role, merged_mcps=merged_m, merged_skills=merged_s)
        m_model = model_name_for_role(role, model_name)
        kwargs: dict[str, Any] = {
            "model_name": m_model,
            "enabled_mcps": mcps,
            "enabled_skills": skills,
            "max_cycles": subtask_max_cycles,
        }
        sid = str(row.get("id", ""))
        _LOG.info(
            "subtask id=%s role=%s enabled_mcps=%s enabled_skills=%s model=%s",
            sid,
            role,
            mcps,
            skills,
            m_model,
        )
        if os.environ.get("LOOMMIND_ORCHESTRATION_LOG_METADATA", "1").lower() not in (
            "0",
            "false",
            "no",
        ):
            print(
                f"[execute_workers] id={sid} role={role} mcps={mcps} skills={skills}",
                flush=True,
            )
        inner = build_graph(**kwargs)
        msgs = _subtask_messages(goal=goal, row=row)
        out = inner.invoke({"messages": msgs})
        draft = last_assistant_draft(list(out["messages"]))
        summaries.append(f"[子任务 {sid}] {draft}".strip())
    return summaries


def run_aggregate(*, model_name: str | None, goal: str, summaries: list[str]) -> str:
    """将子任务输出压缩合并为一段对用户可读文本。"""
    if not summaries:
        return ""
    llm = create_chat_model(model_name)
    packed = "\n\n".join(summaries)
    sys = (
        "你是汇总助手。将下列子任务输出合并为一段中文答复：去重、补全逻辑链，"
        "不要罗列子编号；若信息不足请明确说明缺口。"
    )
    try:
        reply = llm.invoke(
            [
                SystemMessage(content=sys),
                HumanMessage(
                    content=f"用户总目标：\n{goal}\n\n子任务输出：\n{packed}"
                ),
            ]
        )
        c = reply.content
        text = c if isinstance(c, str) else str(c)
        if text.strip():
            return text.strip()
    except Exception:
        _LOG.exception("aggregate LLM 失败，退回拼接")
    return "\n\n".join(summaries)
