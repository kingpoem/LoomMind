"""
将早期会话压缩为摘要并写回 system，保留最近若干条原始消息
压缩会新建一个独立聊天对话修改，同样会消耗 token
"""

import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from api import create_chat_model
from api.runtime_settings import LLMRuntimeSettings
from llm_sanitize import sanitize_messages_for_llm
from prompt_text import load_template_prompt
from settings import get_int

_COMPASS_SUMMARY_SYSTEM = load_template_prompt("compass/summary_system.txt")
_COMPASS_MERGE_HEADING = load_template_prompt("compass/merge_heading.txt")


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
            lines.append(f"  tool_calls: {json.dumps(m.tool_calls, ensure_ascii=False)}")
    return "\n".join(lines)


def _summarize_slice(slice_msgs: list[BaseMessage], *, llm: LLMRuntimeSettings | None = None) -> str:
    model = create_chat_model(llm=llm)
    text = _serialize_for_summary(slice_msgs)
    user_content = load_template_prompt("compass/summary_user.txt").replace("{excerpt}", text)
    reply = model.invoke(
        sanitize_messages_for_llm(
            [
                SystemMessage(content=_COMPASS_SUMMARY_SYSTEM),
                HumanMessage(content=user_content),
            ]
        )
    )
    out = reply.content
    if isinstance(out, str):
        return out.strip()
    return str(out).strip()


def compass_compress(
    messages: list[BaseMessage],
    *,
    keep_last: int | None = None,
    llm: LLMRuntimeSettings | None = None,
) -> tuple[list[BaseMessage], str, str | None]:
    """压缩 system 之后的早期轮次，保留最近 keep_last 条消息。

    返回 (新消息列表, 状态说明, 当次摘要文本或 None；摘要可供写入 memory)。
    """
    k = keep_last if keep_last is not None else get_int("context.compass_keep_last", 8)
    if not messages:
        return messages, "当前无消息。", None

    first = messages[0]
    if not isinstance(first, SystemMessage):
        return messages, "首条不是系统消息，已跳过压缩。", None

    rest = messages[1:]
    if len(rest) <= k:
        return messages, "近期消息不多，无需压缩。", None

    old = rest[:-k]
    recent = rest[-k:]
    summary = _summarize_slice(old, llm=llm)
    if not summary:
        return messages, "摘要为空，未修改历史。", None

    merged = SystemMessage(
        content=first.content + "\n\n" + _COMPASS_MERGE_HEADING + "\n" + summary,
    )
    return (
        [merged, *recent],
        "已压缩早期会话并合并到系统提示。",
        summary,
    )
