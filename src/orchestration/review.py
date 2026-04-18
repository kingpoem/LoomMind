"""顶层审校：压缩、纠错；支持打回重试与上限（M3）。"""

from __future__ import annotations

import json
import re
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from api import create_chat_model

_DEFAULT_MAX_REJECT_RETRIES = 2

_REVIEW_SYSTEM = """你是 LoomMind 的顶层输出审校。
你会收到「用户原始问题」与「下层草稿」（可能啰嗦、重复或含小错误）。
请输出 JSON（仅此一个 JSON 对象，不要 markdown 围栏），字段：
- verdict: 字符串 "accept" 或 "reject"
- final_reply: 字符串。verdict 为 accept 时，为可直接对用户的精炼、纠错后全文；reject 时可为空字符串
- review_notes: 字符串，简短说明（reject 时写打回原因）

规则：
- 草稿基本正确且只需压缩润色 → verdict=accept，final_reply 给对外版本。
- 草稿事实错误明显、严重离题或无法安全发布 → verdict=reject，review_notes 说明问题。
- 若草稿末尾含有字面量子串 ###MOCK_REJECT###（仅用于开发/测试），必须 verdict=reject，review_notes 填 mock_reject。"""


class SupervisorReview(BaseModel):
    """审校结构化输出。"""

    verdict: Literal["accept", "reject"] = Field(
        description="accept 表示可发布；reject 表示需打回重跑下层"
    )
    final_reply: str = Field(default="", description="对外答复正文")
    review_notes: str = Field(default="", description="备注或打回原因")


def last_human_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            c = msg.content
            return c if isinstance(c, str) else str(c)
    return ""


def last_assistant_draft(messages: list[BaseMessage]) -> str:
    """取最后一条可作为「对用户的答复」的 AI 正文（跳过仅含 tool_calls 的 AIMessage）。"""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            if msg.tool_calls:
                continue
            c = msg.content
            return c if isinstance(c, str) else str(c)
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            c = msg.content
            return c if isinstance(c, str) else str(c)
    return ""


def _parse_review_fallback(text: str) -> SupervisorReview:
    """结构化失败时的宽松解析。"""
    raw = text.strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        raw = m.group(0)
    try:
        data = json.loads(raw)
        v = data.get("verdict", "accept")
        if v not in ("accept", "reject"):
            v = "accept"
        return SupervisorReview(
            verdict=v,
            final_reply=str(data.get("final_reply", "")),
            review_notes=str(data.get("review_notes", "")),
        )
    except (json.JSONDecodeError, TypeError):
        return SupervisorReview(
            verdict="accept",
            final_reply=raw,
            review_notes="fallback_plain_text",
        )


def run_structured_review(
    *,
    model_name: str | None,
    user_question: str,
    draft: str,
) -> SupervisorReview:
    """调用模型产出审校结果。"""
    if "###MOCK_REJECT###" in draft:
        return SupervisorReview(
            verdict="reject",
            final_reply="",
            review_notes="mock_reject",
        )

    llm = create_chat_model(model_name)
    structured = llm.with_structured_output(SupervisorReview)
    try:
        out = structured.invoke(
            [
                SystemMessage(content=_REVIEW_SYSTEM),
                HumanMessage(
                    content=json.dumps(
                        {"user_question": user_question, "draft": draft},
                        ensure_ascii=False,
                    )
                ),
            ]
        )
        if isinstance(out, SupervisorReview):
            return out
    except Exception:
        pass
    # 回退：无 structured 或异常时走普通调用再解析
    llm2 = create_chat_model(model_name)
    reply = llm2.invoke(
        [
            SystemMessage(content=_REVIEW_SYSTEM),
            HumanMessage(
                content=json.dumps(
                    {"user_question": user_question, "draft": draft},
                    ensure_ascii=False,
                )
            ),
        ]
    )
    content = reply.content if isinstance(reply.content, str) else str(reply.content)
    return _parse_review_fallback(content)


def run_force_finalize(
    *,
    model_name: str | None,
    user_question: str,
    draft: str,
) -> str:
    """达到打回上限后，强制产出可对外正文（不再 reject）。"""
    sys = (
        "已达到审校重试上限。请基于用户问题与下层草稿，输出一段可直接发布的"
        "精炼中文答复；不得再表示需要打回；修正明显事实错误。"
    )
    llm = create_chat_model(model_name)
    reply = llm.invoke(
        [
            SystemMessage(content=sys),
            HumanMessage(
                content=f"用户问题：\n{user_question}\n\n下层草稿：\n{draft}\n\n请直接输出最终答复正文。"
            ),
        ]
    )
    c = reply.content
    return c if isinstance(c, str) else str(c)


def replace_last_ai_content(messages: list[BaseMessage], text: str) -> list[BaseMessage]:
    out = list(messages)
    for i in range(len(out) - 1, -1, -1):
        if isinstance(out[i], AIMessage):
            out[i] = AIMessage(content=text)
            return out
    return out


__all__ = [
    "SupervisorReview",
    "_DEFAULT_MAX_REJECT_RETRIES",
    "last_assistant_draft",
    "last_human_text",
    "replace_last_ai_content",
    "run_force_finalize",
    "run_structured_review",
]
