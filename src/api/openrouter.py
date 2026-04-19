# https://openrouter.ai/docs

from langchain_openai import ChatOpenAI

from settings import get, get_str


def openrouter_base_url() -> str:
    return get_str("llm.openrouter.base_url", "https://openrouter.ai/api/v1")


def available_models_list() -> list[str]:
    v = get("llm.openrouter.available_models")
    if isinstance(v, list) and v:
        return [str(x) for x in v if isinstance(x, str)]
    return [
        "deepseek/deepseek-chat",
        "deepseek/deepseek-chat-v3.1",
        "qwen/qwen3-30b-a3b",
    ]


def default_openrouter_model() -> str:
    m = get_str("llm.openrouter.default_model").strip()
    if m:
        return m
    models = available_models_list()
    return models[0] if models else "deepseek/deepseek-chat"


def create_openrouter_chat_model(model: str | None = None, *, api_key: str | None = None) -> ChatOpenAI:
    if api_key is not None and api_key.strip():
        key = api_key.strip()
    else:
        key = get_str("llm.openrouter.api_key").strip()
    return ChatOpenAI(
        model=(model or default_openrouter_model()).strip(),
        openai_api_key=key,
        openai_api_base=openrouter_base_url(),
        temperature=0,
    )
