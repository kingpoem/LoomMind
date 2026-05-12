"""会话级 LLM 配置覆盖（优先于 settings.json）。"""

from dataclasses import dataclass

from .provider import LLMProvider, resolve_llm_provider


@dataclass
class LLMRuntimeSettings:
    """未设置的字段回退到 settings.json。"""

    provider: LLMProvider | None = None
    openrouter_api_key: str | None = None
    ollama_base_url: str | None = None
    deepseek_api_key: str | None = None

    def effective_provider(self) -> LLMProvider:
        if self.provider is not None:
            return self.provider
        return resolve_llm_provider()
