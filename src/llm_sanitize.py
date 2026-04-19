"""发往 OpenAI 兼容 API（含 Ollama）前净化消息文本。

孤立 UTF-16 代理项（U+D800–U+DFFF 中单个码位）不是合法 Unicode 标量，JSON/HTTP 严格 UTF-8
编码会失败；来源可能是 memory 文件、模板或模型流式输出。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage


def utf8_safe_str(s: str) -> str:
    return s.encode("utf-8", errors="replace").decode("utf-8")


def _sanitize_block(block: dict[str, Any]) -> dict[str, Any]:
    out = dict(block)
    if out.get("type") == "text" and isinstance(out.get("text"), str):
        out["text"] = utf8_safe_str(out["text"])
    return out


def sanitize_message_content(content: str | list[Any] | Any) -> str | list[Any] | Any:
    if isinstance(content, str):
        return utf8_safe_str(content)
    if isinstance(content, list):
        fixed: list[Any] = []
        for x in content:
            if isinstance(x, dict):
                fixed.append(_sanitize_block(x))
            else:
                fixed.append(x)
        return fixed
    return content


def sanitize_message(msg: BaseMessage) -> BaseMessage:
    new_content = sanitize_message_content(msg.content)
    if new_content is msg.content:
        return msg
    return msg.model_copy(update={"content": new_content})


def sanitize_messages_for_llm(messages: list[BaseMessage]) -> list[BaseMessage]:
    return [sanitize_message(m) for m in messages]
