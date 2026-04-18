"""顶层 triage：无 LLM，纯规则，满足 M2 验收用例。"""

from __future__ import annotations

from typing import Literal

RouteKey = Literal["simple", "complex"]

_COMPLEX_HINTS: tuple[str, ...] = (
    "调研",
    "分步",
    "三步",
    "多步",
    "子任务",
    "拆解",
    "计划",
    "执行计划",
    "工具",
    "调用工具",
    "实现",
    "代码",
    "写代码",
    "文件",
    "详细分析",
    "对比",
    "评估",
    "架构",
    "设计文档",
    "排查",
    "调试",
)


def triage_route_from_text(text: str) -> RouteKey:
    """根据用户本轮文本判定路由。

    - 「你好」类短问候 → simple
    - 「请分三步调研…」等含复杂线索 → complex
    """
    t = (text or "").strip()
    if any(h in t for h in _COMPLEX_HINTS):
        return "complex"
    if len(t) > 200:
        return "complex"

    tl = t.lower()
    if len(t) <= 32:
        if any(x in tl for x in ("hello", "hi", "hey")):
            return "simple"
    if len(t) <= 24:
        for g in (
            "你好",
            "您好",
            "嗨",
            "谢谢",
            "感谢",
            "再见",
            "拜拜",
            "早上好",
            "晚上好",
            "午安",
        ):
            if g in t:
                return "simple"
    if len(t) <= 14 and not any(ch.isdigit() for ch in t):
        return "simple"
    return "complex"
