"""规划循环：thought -> action -> observation -> next step。"""

import re
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
from api.runtime_settings import LLMRuntimeSettings
from llm_sanitize import sanitize_messages_for_llm
from prompt_text import load_template_prompt
from settings import get_int, get_optional_int

from .exit_signal import take_exit
from .memory import append_long_term_memory, read_long_term_memories
from .todo import get_context_block as _get_todo_block


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
    task_outline: NotRequired[list[str]]


def resolve_planning_max_cycles(override: int | None = None) -> int:
    """解析规划循环上限。

    显式参数优先，否则读 `planning.max_cycles`，再退回
    `planning.default_max_cycles`。
    """
    cap = get_int("planning.max_cycles_cap", 64)
    default_n = get_int("planning.default_max_cycles", 6)
    if override is not None:
        return max(1, min(int(override), cap))
    raw = get_optional_int("planning.max_cycles")
    if raw is None:
        return default_n
    return max(1, min(int(raw), cap))


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


def _extract_task_outline(text: str) -> list[str]:
    """从首轮模型正文中抽取编号行或列表行，作为可验证子目标（启发式）。"""
    out: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)[\.\、\)]\s*(.+)$", line)
        if m:
            out.append(_clip(m.group(2), limit=160))
            continue
        m2 = re.match(r"^[-*•]\s+(.+)$", line)
        if m2:
            out.append(_clip(m2.group(1), limit=160))
    n = get_int("planning.task_outline_max", 12)
    return out[:n]


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


def _append_trace(trace: list[PlanningTrace], *, node: str, content: str) -> list[PlanningTrace]:
    lim = get_int("planning.trace_limit", 16)
    updated = [*trace, {"node": node, "content": _clip(content, limit=260)}]
    return updated[-lim:]


def _merge_block_into_first_system(messages: list[BaseMessage], block: str, *, heading: str) -> list[BaseMessage]:
    """把附加段落合并进第一条 SystemMessage。

    Ollama 的 OpenAI 兼容层在「System → Human → System」顺序下常把助手解析成空 content；
    规划轮次必须把上下文并入首条系统提示，而不是再追加一条 System。
    """
    suffix = f"\n\n{heading}{block}".rstrip()
    out: list[BaseMessage] = []
    merged = False
    for m in messages:
        if not merged and isinstance(m, SystemMessage):
            merged = True
            c = m.content
            if isinstance(c, str):
                out.append(SystemMessage(content=c + suffix))
            else:
                out.append(m)
        else:
            out.append(m)
    if not merged:
        out.insert(0, SystemMessage(content=suffix.strip()))
    return out


def _memory_hint(
    short_mem: list[str],
    long_mem: list[str],
    *,
    cycle: int,
    limit: int,
    task_outline: list[str],
) -> str:
    st_lim = get_int("planning.short_term_limit", 8)
    short = "\n".join(f"- {item}" for item in short_mem[-st_lim:]) or "- 无"
    long = "\n".join(f"- {item}" for item in long_mem[-6:]) or "- 无"
    outline_block = ""
    if task_outline:
        ol = "\n".join(f"- {item}" for item in task_outline)
        outline_block = "\n\n" + load_template_prompt("planning/task_outline_block.txt").replace("{outline}", ol) + "\n"

    base = load_template_prompt("planning/thought_context.txt") + "\n"

    nearing = ""
    if limit > 1 and cycle >= max(0, limit - 2):
        nearing = "\n" + load_template_prompt("planning/nearing_limit.txt").format(cycle=cycle, limit=limit)

    todo_block = _get_todo_block()
    todo_section = ("\n\n" + todo_block) if todo_block else ""

    return f"{base}{nearing}{outline_block}短期记忆（本轮）:\n{short}\n\n长期记忆（跨轮）:\n{long}{todo_section}"


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
    outline = state.get("task_outline") or []
    outline_s = ""
    if outline:
        outline_s = "；子目标=" + _clip(" | ".join(outline), limit=200)
    return f"目标={goal or '未提取'}{outline_s}；观察={observation}；结果={answer or '未提取'}"


def build_planning_graph(
    *,
    model_name: str | None = None,
    tools: Iterable[BaseTool] = (),
    max_cycles: int | None = None,
    llm_settings: LLMRuntimeSettings | None = None,
):
    tool_list = list(tools)
    graph_max_cycles = resolve_planning_max_cycles(max_cycles)
    base_model = create_chat_model(model_name, llm=llm_settings)
    thought_model = base_model.bind_tools(tool_list) if tool_list else base_model

    def thought(state: PlanningState) -> dict:
        short_mem = list(state.get("short_term_memory", []))
        long_mem = list(state.get("long_term_memory", [])) or read_long_term_memories()
        trace = list(state.get("planning_trace", []))
        cycle = int(state.get("cycle_count", 0))
        limit = int(state.get("max_cycles", graph_max_cycles))
        outline = list(state.get("task_outline", []))
        planner_body = _memory_hint(short_mem, long_mem, cycle=cycle, limit=limit, task_outline=outline) + f"\n\n当前循环次数: {cycle}/{limit}。"
        to_invoke = _merge_block_into_first_system(
            list(state["messages"]),
            planner_body,
            heading="## 规划上下文\n",
        )
        reply: AIMessage = thought_model.invoke(sanitize_messages_for_llm(to_invoke))
        if cycle == 0 and not outline:
            extracted = _extract_task_outline(_msg_text(reply))
            if extracted:
                outline = extracted
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
            "task_outline": outline,
        }

    def observation(state: PlanningState) -> dict:
        short_mem = list(state.get("short_term_memory", []))
        trace = list(state.get("planning_trace", []))

        exit_signal = take_exit()
        if exit_signal is not None:
            tool_name, message = exit_signal
            trace = _append_trace(trace, node="observation", content=f"{tool_name}: {_clip(message)}")
            return {
                "messages": [AIMessage(content=message)],
                "short_term_memory": short_mem,
                "planning_trace": trace,
                "exit_reason": tool_name,
            }

        observed = _summarize_tool_observation(_latest_tool_messages(state["messages"]))
        if not observed:
            return {"short_term_memory": short_mem, "planning_trace": trace}
        st_lim = get_int("planning.short_term_limit", 8)
        short_mem = [*short_mem, observed][-st_lim:]
        if any(token in observed.lower() for token in ("error", "failed", "traceback")):
            short_mem = [
                *short_mem,
                load_template_prompt("planning/tool_failure_hint.txt"),
            ][-st_lim:]
        trace = _append_trace(trace, node="observation", content=observed)
        return {"short_term_memory": short_mem, "planning_trace": trace}

    def next_step(state: PlanningState) -> dict:
        cycle = int(state.get("cycle_count", 0)) + 1
        limit = int(state.get("max_cycles", graph_max_cycles))
        trace = list(state.get("planning_trace", []))
        reason = state.get("exit_reason", "")
        if reason in _TOOL_EXIT_REASONS:
            detail = f"工具退出: {reason}"
        elif cycle >= limit:
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
        outline = list(state.get("task_outline", []))
        outline_txt = "\n".join(f"- {x}" for x in outline) if outline else "无"
        short_mem_s = "\n".join(short_mem) or "无"
        long_mem_s = "\n".join(long_mem) or "无"
        fin = load_template_prompt("planning/finalize.txt")
        fin = fin.replace("{outline_txt}", outline_txt).replace("{short_mem}", short_mem_s).replace("{long_mem}", long_mem_s)
        finalize_prompt = HumanMessage(content=fin)
        reply: AIMessage = base_model.invoke(sanitize_messages_for_llm([*state["messages"], finalize_prompt]))
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

    _TOOL_EXIT_REASONS = frozenset({"ask_user", "finish_task"})

    def route_after_next_step(state: PlanningState) -> str:
        reason = state.get("exit_reason", "")
        if reason in _TOOL_EXIT_REASONS:
            return "remember"
        if reason == "max_cycles_reached":
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
            {"finalize": "finalize", "thought": "thought", "remember": "remember"},
        )
        g.add_edge("finalize", "remember")
    else:
        g.add_edge("thought", "remember")

    g.add_edge("remember", END)
    return g.compile()
