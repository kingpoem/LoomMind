"""编排层 LangGraph（M2–M7）：预处理 → 路由 → worker → 审校。"""

from __future__ import annotations

import copy
import json
import logging
import os
from collections.abc import Iterable

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from api import create_chat_model
from planning import resolve_planning_max_cycles

from .context_trim import messages_for_simple_invoke
from .metadata import build_orchestration_metadata
from .module_supervisor import run_aggregate, run_decompose, run_execute_workers
from .review import (
    _DEFAULT_MAX_REJECT_RETRIES,
    last_assistant_draft,
    last_human_text,
    replace_last_ai_content,
    run_force_finalize,
    run_structured_review,
)
from .state import OrchestrationState
from .strategic import apply_strategic_layer, normalize_allowlist

_LOG = logging.getLogger(__name__)


def build_orchestration_graph(
    *,
    model_name: str | None = None,
    enabled_skills: Iterable[str] | None = None,
    enabled_mcps: Iterable[str] | None = None,
    max_cycles: int | None = None,
    max_review_reject_retries: int = _DEFAULT_MAX_REJECT_RETRIES,
):
    """构建外层编排图。

    - **complex** 路径：`strategic_agent` → `decompose` → `execute_workers` → `aggregate`
      → `total_supervisor_review`（子图不复用父级全量 messages）。
    """
    _base_chat = create_chat_model(model_name)
    try:
        simple_llm = _base_chat.bind_tools([], tool_choice="none")
    except (TypeError, ValueError):
        simple_llm = _base_chat
    _base_mcps = normalize_allowlist(enabled_mcps)
    _base_skills = normalize_allowlist(enabled_skills)
    _parent_cycles = resolve_planning_max_cycles(max_cycles)
    _raw_sub = os.environ.get("LOOMMIND_SUBTASK_MAX_PLAN_CYCLES", "").strip()
    if _raw_sub:
        try:
            _subtask_cycles = max(1, min(int(_raw_sub), 64))
        except ValueError:
            _subtask_cycles = max(3, min(_parent_cycles, 8))
    else:
        _subtask_cycles = max(3, min(_parent_cycles, 8))

    def total_supervisor_preprocess(state: OrchestrationState) -> dict:
        user_text = last_human_text(state["messages"])
        meta = build_orchestration_metadata(state["messages"], user_text)
        payload = json.dumps(meta, ensure_ascii=False)
        _LOG.info("orchestration_metadata %s", payload)
        if os.environ.get("LOOMMIND_ORCHESTRATION_LOG_METADATA", "1").lower() not in (
            "0",
            "false",
            "no",
        ):
            print(f"[orchestration_metadata] {payload}", flush=True)
        return {
            "orchestration_metadata": meta,
            "messages_checkpoint": copy.deepcopy(state["messages"]),
            "reject_retry_count": 0,
            "max_review_reject_retries": max_review_reject_retries,
        }

    def orchestration_router(state: OrchestrationState) -> dict:
        meta = state.get("orchestration_metadata") or {}
        route = meta.get("suggested_route", "complex")
        if route not in ("simple", "complex"):
            route = "complex"
        return {"orchestration_route": route}

    def strategic_agent(state: OrchestrationState) -> dict:
        meta = state.get("orchestration_metadata") or {}
        task = str(meta.get("task_text", "") or "")
        delta = apply_strategic_layer(
            task_text=task,
            metadata=meta,
            base_mcps=_base_mcps,
            base_skills=_base_skills,
        )
        sug = delta.get("orchestration_metadata", {}).get("tool_injection_suggestions", [])
        _LOG.info("strategic_agent suggestions=%s", sug)
        if os.environ.get("LOOMMIND_ORCHESTRATION_LOG_METADATA", "1").lower() not in (
            "0",
            "false",
            "no",
        ):
            print(f"[strategic_agent] {json.dumps(sug, ensure_ascii=False)}", flush=True)
        return delta

    def direct_simple(state: OrchestrationState) -> dict:
        win = messages_for_simple_invoke(state["messages"])
        reply: AIMessage = simple_llm.invoke(win)
        return {"messages": [*state["messages"], reply]}

    def decompose(state: OrchestrationState) -> dict:
        goal = last_human_text(state["messages"])
        rows, _g = run_decompose(model_name=model_name, user_goal=goal)
        if os.environ.get("LOOMMIND_ORCHESTRATION_LOG_METADATA", "1").lower() not in (
            "0",
            "false",
            "no",
        ):
            print(
                f"[module_supervisor.decompose] n={len(rows)} ids={[r.get('id') for r in rows]}",
                flush=True,
            )
        return {
            "subtasks": rows,
            "module_user_goal": goal,
            "worker_summaries": [],
        }

    def execute_workers(state: OrchestrationState) -> dict:
        goal = str(state.get("module_user_goal") or last_human_text(state["messages"]))
        rows = list(state.get("subtasks") or [])
        cm = state.get("complex_enabled_mcps")
        cs = state.get("complex_enabled_skills")
        cmc = list(cm) if isinstance(cm, list) else None
        csk = list(cs) if isinstance(cs, list) else None
        summaries = run_execute_workers(
            model_name=model_name,
            enabled_skills=enabled_skills,
            enabled_mcps=enabled_mcps,
            complex_enabled_mcps=cmc,
            complex_enabled_skills=csk,
            subtask_max_cycles=_subtask_cycles,
            goal=goal,
            subtasks=rows,
        )
        if os.environ.get("LOOMMIND_ORCHESTRATION_LOG_METADATA", "1").lower() not in (
            "0",
            "false",
            "no",
        ):
            print(
                f"[module_supervisor.execute_workers] summaries={len(summaries)}",
                flush=True,
            )
        return {"worker_summaries": summaries}

    def aggregate(state: OrchestrationState) -> dict:
        goal = str(state.get("module_user_goal") or last_human_text(state["messages"]))
        summaries = list(state.get("worker_summaries") or [])
        text = run_aggregate(
            model_name=model_name, goal=goal, summaries=summaries
        )
        if not text.strip():
            text = "（子任务未产生可汇总输出）"
        return {"messages": [*state["messages"], AIMessage(content=text)]}

    def total_supervisor_review(state: OrchestrationState) -> dict:
        user_q = last_human_text(state["messages"])
        draft = last_assistant_draft(state["messages"])
        cap = int(state.get("max_review_reject_retries") or _DEFAULT_MAX_REJECT_RETRIES)
        r = int(state.get("reject_retry_count") or 0)

        result = run_structured_review(
            model_name=model_name,
            user_question=user_q,
            draft=draft,
        )

        if result.verdict == "accept" and (result.final_reply or "").strip():
            final_text = result.final_reply.strip()
            new_msgs = replace_last_ai_content(state["messages"], final_text)
            return {
                "messages": new_msgs,
                "review_verdict": "accept",
                "exit_reason": "review_accept",
                "after_review_route": "end",
            }

        if result.verdict == "accept" and not (result.final_reply or "").strip():
            new_msgs = replace_last_ai_content(state["messages"], draft.strip())
            return {
                "messages": new_msgs,
                "review_verdict": "accept",
                "exit_reason": "review_accept_unchanged",
                "after_review_route": "end",
            }

        if r >= cap:
            forced = run_force_finalize(
                model_name=model_name,
                user_question=user_q,
                draft=draft,
            ).strip()
            new_msgs = replace_last_ai_content(
                state["messages"], forced or draft.strip()
            )
            return {
                "messages": new_msgs,
                "review_verdict": "accept",
                "exit_reason": "review_cap",
                "after_review_route": "end",
            }

        cp = state.get("messages_checkpoint") or list(state["messages"])
        route = state.get("orchestration_route", "complex")
        return {
            "messages": copy.deepcopy(cp),
            "reject_retry_count": r + 1,
            "review_verdict": "reject",
            "exit_reason": "review_reject_retry",
            "after_review_route": (
                "retry_simple" if route == "simple" else "retry_complex"
            ),
            "subtasks": [],
            "worker_summaries": [],
            "module_user_goal": "",
        }

    def route_after_router(state: OrchestrationState) -> str:
        r = state.get("orchestration_route", "complex")
        return "direct_simple" if r == "simple" else "strategic_agent"

    def route_after_review(state: OrchestrationState) -> str:
        key = state.get("after_review_route", "end")
        if key == "retry_simple":
            return "direct_simple"
        if key == "retry_complex":
            return "strategic_agent"
        return "end"

    g = StateGraph(OrchestrationState)
    g.add_node("total_supervisor_preprocess", total_supervisor_preprocess)
    g.add_node("orchestration_router", orchestration_router)
    g.add_node("strategic_agent", strategic_agent)
    g.add_node("direct_simple", direct_simple)
    g.add_node("decompose", decompose)
    g.add_node("execute_workers", execute_workers)
    g.add_node("aggregate", aggregate)
    g.add_node("total_supervisor_review", total_supervisor_review)

    g.add_edge(START, "total_supervisor_preprocess")
    g.add_edge("total_supervisor_preprocess", "orchestration_router")
    g.add_conditional_edges(
        "orchestration_router",
        route_after_router,
        {
            "direct_simple": "direct_simple",
            "strategic_agent": "strategic_agent",
        },
    )
    g.add_edge("strategic_agent", "decompose")
    g.add_edge("decompose", "execute_workers")
    g.add_edge("execute_workers", "aggregate")
    g.add_edge("aggregate", "total_supervisor_review")
    g.add_edge("direct_simple", "total_supervisor_review")
    g.add_conditional_edges(
        "total_supervisor_review",
        route_after_review,
        {
            "direct_simple": "direct_simple",
            "strategic_agent": "strategic_agent",
            "end": END,
        },
    )
    return g.compile()
