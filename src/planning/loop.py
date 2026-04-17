"""规划循环：thought -> action -> observation -> next step。"""

from collections.abc import Iterable
from typing import Annotated, NotRequired, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from api import create_chat_model

from .memory import append_long_term_memory, read_long_term_memories

_DEFAULT_MAX_CYCLES = 6
_SHORT_TERM_LIMIT = 8
_TRACE_LIMIT = 16


class PlanningTrace(TypedDict):
    node: str
    content: str


class PlanningState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    short_term_memory: NotRequired[list[str]]
    long_term_memory: NotRequired[list[str]]
    planning_trace: NotRequired[list[PlanningTrace]]
    cycle_count: NotRequired[int]
    max_cycles: NotRequired[int]
    exit_reason: NotRequired[str]


def _clip(text: str, *, limit: int = 220) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "…"


def _msg_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return str(content)


def _latest_tool_messages(messages: list[BaseMessage]) -> list[ToolMessage]:
    items: list[ToolMessage] = []
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            items.append(msg)
            continue
        break
    items.reverse()
    return items


def _summarize_tool_observation(messages: list[ToolMessage]) -> str:
    if not messages:
        return ""
    lines = []
    for msg in messages:
        name = getattr(msg, "name", "") or "tool"
        lines.append(f"{name}: {_clip(_msg_text(msg), limit=180)}")
    return " | ".join(lines)


def _append_trace(
    trace: list[PlanningTrace], *, node: str, content: str
) -> list[PlanningTrace]:
    updated = [*trace, {"node": node, "content": _clip(content, limit=260)}]
    return updated[-_TRACE_LIMIT:]


def _memory_hint(short_mem: list[str], long_mem: list[str]) -> str:
    short = "\n".join(f"- {item}" for item in short_mem[-_SHORT_TERM_LIMIT:]) or "- 无"
    long = "\n".join(f"- {item}" for item in long_mem[-6:]) or "- 无"
    return (
        "你正在执行规划循环：thought -> action -> observation -> next step。\n"
        "优先做任务拆解；遇到失败时先自我修正再继续。\n"
        "若信息足够可直接给结论，不必强行调用工具。\n\n"
        "短期记忆（本轮）:\n"
        f"{short}\n\n"
        "长期记忆（跨轮）:\n"
        f"{long}"
    )


def _build_long_term_entry(state: PlanningState) -> str:
    goal = ""
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            goal = _clip(_msg_text(msg), limit=140)
            break
    short_mem = list(state.get("short_term_memory", []))
    observation = short_mem[-1] if short_mem else "无"
    answer = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, AIMessage):
            answer = _clip(_msg_text(msg), limit=180)
            break
    return f"目标={goal or '未提取'}；观察={observation}；结果={answer or '未提取'}"


def build_planning_graph(
    *,
    model_name: str | None = None,
    tools: Iterable[BaseTool] = (),
    max_cycles: int = _DEFAULT_MAX_CYCLES,
):
    tool_list = list(tools)
    base_model = create_chat_model(model_name)
    thought_model = base_model.bind_tools(tool_list) if tool_list else base_model

    def thought(state: PlanningState) -> dict:
        short_mem = list(state.get("short_term_memory", []))
        long_mem = list(state.get("long_term_memory", [])) or read_long_term_memories()
        trace = list(state.get("planning_trace", []))
        cycle = int(state.get("cycle_count", 0))
        limit = int(state.get("max_cycles", max_cycles))
        planner_system = SystemMessage(
            content=_memory_hint(short_mem, long_mem)
            + f"\n\n当前循环次数: {cycle}/{limit}。"
        )
        reply: AIMessage = thought_model.invoke([*state["messages"], planner_system])
        step = "调用工具" if reply.tool_calls else "直接回答"
        trace = _append_trace(
            trace,
            node="thought",
            content=f"{step}: {_clip(_msg_text(reply))}",
        )
        return {
            "messages": [reply],
            "short_term_memory": short_mem,
            "long_term_memory": long_mem,
            "planning_trace": trace,
            "cycle_count": cycle,
            "max_cycles": limit,
        }

    def observation(state: PlanningState) -> dict:
        short_mem = list(state.get("short_term_memory", []))
        trace = list(state.get("planning_trace", []))
        observed = _summarize_tool_observation(_latest_tool_messages(state["messages"]))
        if not observed:
            return {"short_term_memory": short_mem, "planning_trace": trace}
        short_mem = [*short_mem, observed][-_SHORT_TERM_LIMIT:]
        if any(token in observed.lower() for token in ("error", "failed", "traceback")):
            short_mem = [
                *short_mem,
                "检测到失败迹象，下一步先调整参数或切换方案后再行动。",
            ][-_SHORT_TERM_LIMIT:]
        trace = _append_trace(trace, node="observation", content=observed)
        return {"short_term_memory": short_mem, "planning_trace": trace}

    def next_step(state: PlanningState) -> dict:
        cycle = int(state.get("cycle_count", 0)) + 1
        limit = int(state.get("max_cycles", max_cycles))
        trace = list(state.get("planning_trace", []))
        reason = state.get("exit_reason", "")
        if cycle >= limit:
            reason = "max_cycles_reached"
            detail = "达到退出条件：循环上限"
        else:
            detail = "继续下一轮 thought"
        trace = _append_trace(trace, node="next_step", content=detail)
        return {"cycle_count": cycle, "exit_reason": reason, "planning_trace": trace}

    def force_finalize(state: PlanningState) -> dict:
        trace = list(state.get("planning_trace", []))
        short_mem = list(state.get("short_term_memory", []))
        long_mem = list(state.get("long_term_memory", []))
        finalize_prompt = SystemMessage(
            content=(
                "达到规划循环退出条件（最大循环次数），"
                "现在请基于现有信息直接给最终答复，禁止继续调用工具。\n\n"
                f"短期记忆:\n{chr(10).join(short_mem) or '无'}\n\n"
                f"长期记忆:\n{chr(10).join(long_mem) or '无'}"
            )
        )
        reply: AIMessage = base_model.invoke([*state["messages"], finalize_prompt])
        trace = _append_trace(
            trace,
            node="thought",
            content=f"退出收敛: {_clip(_msg_text(reply))}",
        )
        return {"messages": [reply], "planning_trace": trace}

    def remember(state: PlanningState) -> dict:
        if int(state.get("cycle_count", 0)) <= 0:
            return {}
        try:
            append_long_term_memory(_build_long_term_entry(state))
        except OSError:
            return {}
        return {"long_term_memory": read_long_term_memories()}

    def route_after_thought(state: PlanningState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "action"
        return "remember"

    def route_after_next_step(state: PlanningState) -> str:
        if state.get("exit_reason") == "max_cycles_reached":
            return "finalize"
        return "thought"

    g = StateGraph(PlanningState)
    g.add_node("thought", thought)
    g.add_node("remember", remember)
    g.add_edge(START, "thought")

    if tool_list:
        g.add_node("action", ToolNode(tool_list))
        g.add_node("observation", observation)
        g.add_node("next_step", next_step)
        g.add_node("finalize", force_finalize)

        g.add_conditional_edges(
            "thought",
            route_after_thought,
            {"action": "action", "remember": "remember"},
        )
        g.add_edge("action", "observation")
        g.add_edge("observation", "next_step")
        g.add_conditional_edges(
            "next_step",
            route_after_next_step,
            {"finalize": "finalize", "thought": "thought"},
        )
        g.add_edge("finalize", "remember")
    else:
        g.add_edge("thought", "remember")

    g.add_edge("remember", END)
    return g.compile()
