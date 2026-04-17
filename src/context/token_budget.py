"""会话上下文 token 估算"""

import json
from functools import lru_cache

import tiktoken
from langchain_core.messages import AIMessage, BaseMessage

TOKEN_CONTEXT_LIMIT = 100_000


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
