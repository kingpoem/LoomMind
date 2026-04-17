"""
将早期会话压缩为摘要并写回 system，保留最近若干条原始消息
压缩会新建一个独立聊天对话修改，同样会消耗 token
"""

import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from api import create_chat_model

_COMPASS_SUMMARY_SYSTEM = (
    "你是会话整理助手。将下列对话节选压缩为简洁中文摘要，保留：关键事实、用户目标、"
    "已达成共识、待办与约束、术语与数据；删去寒暄与重复。只输出摘要正文，不要标题或套话。"
)

_DEFAULT_KEEP_LAST = 8


def _serialize_for_summary(msgs: list[BaseMessage]) -> str:
    lines: list[str] = []
    for m in msgs:
        role = m.type
        content = m.content
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        elif not isinstance(content, str):
            content = str(content)
        lines.append(f"[{role}] {content}")
        if isinstance(m, AIMessage) and m.tool_calls:
            lines.append(
                f"  tool_calls: {json.dumps(m.tool_calls, ensure_ascii=False)}"
            )
    return "\n".join(lines)


def _summarize_slice(slice_msgs: list[BaseMessage]) -> str:
    model = create_chat_model()
    text = _serialize_for_summary(slice_msgs)
    reply = model.invoke(
        [
            SystemMessage(content=_COMPASS_SUMMARY_SYSTEM),
            HumanMessage(
                content="请压缩以下对话节选：\n\n---\n" + text + "\n---",
            ),
        ]
    )
    out = reply.content
    if isinstance(out, str):
        return out.strip()
    return str(out).strip()


def compass_compress(
    messages: list[BaseMessage],
    *,
    keep_last: int = _DEFAULT_KEEP_LAST,
) -> tuple[list[BaseMessage], str]:
    """压缩 system 之后的早期轮次，保留最近 keep_last 条消息。

    返回 (新消息列表, 状态说明)。
    """
    if not messages:
        return messages, "当前无消息。"

    first = messages[0]
    if not isinstance(first, SystemMessage):
        return messages, "首条不是系统消息，已跳过压缩。"

    rest = messages[1:]
    if len(rest) <= keep_last:
        return messages, "近期消息不多，无需压缩。"

    old = rest[:-keep_last]
    recent = rest[-keep_last:]
    summary = _summarize_slice(old)
    if not summary:
        return messages, "摘要为空，未修改历史。"

    merged = SystemMessage(
        content=first.content + "\n\n【较早对话摘要】\n" + summary,
    )
    return [merged, *recent], "已压缩早期会话并合并到系统提示。"
