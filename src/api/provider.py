"""LLM 提供方：由 settings.json 解析，供 api 层统一分支。"""

from enum import StrEnum

from settings import get_str


class LLMProvider(StrEnum):
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"


def resolve_llm_provider() -> LLMProvider:
    """读取 `llm.provider`（settings.json）。

    - 未设置、空串、`openrouter` → OpenRouter；
    - `ollama` → 本地 Ollama；
    - 其它未知值 → 回退为 OpenRouter（避免拼写错误导致进程无法启动）。
    """
    raw = get_str("llm.provider").strip().lower()
    if raw == LLMProvider.OLLAMA:
        return LLMProvider.OLLAMA
    if raw in ("", LLMProvider.OPENROUTER):
        return LLMProvider.OPENROUTER
    return LLMProvider.OPENROUTER
