"""按路由裁剪送入 worker 的 messages（M4/M6）：simple 小窗口 + 无工具上下文净化。"""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

# simple：仅保留首条 SystemMessage + 末尾若干条（硬编码，与 complex 区分）
_SIMPLE_TAIL_MESSAGES = 8
# complex：M5 起与战略层一致，硬编码「最近 K 条」（含 System 时为首条 + 末尾 K）
_COMPLEX_TAIL_MESSAGES = 40


def messages_for_worker(
    full: list[BaseMessage],
    route: Literal["simple", "complex"],
) -> list[BaseMessage]:
    """返回本轮传给 `direct_simple` / `complex_placeholder` 的上下文（仅裁剪）。"""
    if not full:
        return full
    first = full[0]
    rest = full[1:]
    budget = _SIMPLE_TAIL_MESSAGES if route == "simple" else _COMPLEX_TAIL_MESSAGES
    if isinstance(first, SystemMessage):
        if len(rest) <= budget:
            return list(full)
        return [first, *rest[-budget:]]
    if len(full) <= budget:
        return list(full)
    return full[-budget:]


def messages_for_simple_invoke(full: list[BaseMessage]) -> list[BaseMessage]:
    """simple 路径专用：短窗口 + 去掉 ToolMessage + 去掉历史 AIMessage 的 tool_calls。

    避免模型在问候等场景看到工具协议形态而产生幻觉式 tool_calls。
    """
    trimmed = messages_for_worker(full, "simple")
    out: list[BaseMessage] = []
    for m in trimmed:
        if isinstance(m, ToolMessage):
            continue
        if isinstance(m, AIMessage) and m.tool_calls:
            text = m.content if isinstance(m.content, str) else str(m.content)
            out.append(
                AIMessage(
                    content=(text or "").strip() or "（上一轮模型输出已省略）",
                )
            )
            continue
        out.append(m)
    if out and isinstance(out[0], SystemMessage):
        c = out[0].content
        if isinstance(c, str) and "编排约束" not in c:
            guard = (
                "\n\n【编排约束】本路径为简单对话：禁止调用任何工具；"
                "不要输出 tool_calls。"
            )
            out[0] = SystemMessage(content=c + guard)
    return out
