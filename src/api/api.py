from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from .ollama import (
    create_ollama_chat_model,
    default_ollama_model,
    list_ollama_models,
)
from .openrouter import (
    available_models_list,
    create_openrouter_chat_model,
    default_openrouter_model,
)
from .provider import LLMProvider, resolve_llm_provider
from .runtime_settings import LLMRuntimeSettings


def create_chat_model(model: str | None = None, *, llm: LLMRuntimeSettings | None = None) -> ChatOpenAI:
    provider = llm.effective_provider() if llm else resolve_llm_provider()
    if provider is LLMProvider.OLLAMA:
        return create_ollama_chat_model(
            model=model,
            api_key=llm.ollama_api_key if llm else None,
            base_url_override=llm.ollama_base_url if llm else None,
        )
    return create_openrouter_chat_model(
        model=model,
        api_key=llm.openrouter_api_key if llm else None,
    )


def list_available_models(*, llm: LLMRuntimeSettings | None = None) -> list[str]:
    provider = llm.effective_provider() if llm else resolve_llm_provider()
    if provider is LLMProvider.OLLAMA:
        return list_ollama_models(
            base_url_override=llm.ollama_base_url if llm else None,
        )
    return list(available_models_list())


def default_model_name(*, llm: LLMRuntimeSettings | None = None) -> str:
    provider = llm.effective_provider() if llm else resolve_llm_provider()
    if provider is LLMProvider.OLLAMA:
        return default_ollama_model(
            base_url_override=llm.ollama_base_url if llm else None,
        )
    return default_openrouter_model()


def invoke(
    messages: list[BaseMessage],
    model: str | None = None,
    *,
    llm: LLMRuntimeSettings | None = None,
) -> BaseMessage:
    return create_chat_model(model=model, llm=llm).invoke(messages)
