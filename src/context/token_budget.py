"""会话上下文 token 估算"""

import json
from functools import lru_cache

import tiktoken
from langchain_core.messages import AIMessage, BaseMessage

from settings import get, get_int


def token_context_limit() -> int:
    return get_int("context.token_context_limit", 100_000)


def token_auto_compress_ratio() -> float:
    """自动压缩触发比例：当前对话（含本轮用户输入）超过 `limit * ratio` 时尝试 compass。

    返回 0.0 表示关闭（`settings.json` 中 `context.auto_compress_ratio` 为 null）。
    默认 0.8；若写成大于 1 的数字则按百分数理解（如 80 表示 80%）。
    """
    v = get("context.auto_compress_ratio", 0.8)
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 0.8 if v else 0.0
    if isinstance(v, (int, float)):
        x = float(v)
        if x <= 0:
            return 0.0
        if x > 1.0:
            return min(0.99, x / 100.0)
        return x
    return 0.8


def token_auto_compress_max_rounds() -> int:
    """单次用户消息内，自动压缩最多连续执行几次 compass（防止死循环）。

    配置项：`context.auto_compress_max_rounds`，默认 5，范围 1～64。
    """
    n = get_int("context.auto_compress_max_rounds", 5)
    return max(1, min(n, 64))


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def _text_for_count(m: BaseMessage) -> str:
    parts: list[str] = []
    content = m.content
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
    if isinstance(m, AIMessage) and m.tool_calls:
        parts.append(json.dumps(m.tool_calls, ensure_ascii=False))
    return "\n".join(parts)


def count_messages_tokens(messages: list[BaseMessage]) -> int:
    enc = _encoding()
    return sum(len(enc.encode(_text_for_count(m) or "")) for m in messages)
