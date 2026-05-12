"""DeepSeek 官方 API provider."""

from langchain_openai import ChatOpenAI

from settings import get, get_str


def deepseek_base_url() -> str:
    return get_str("llm.deepseek.base_url", "https://api.deepseek.com").rstrip("/")


def available_models_list() -> list[str]:
    v = get("llm.deepseek.available_models")
    if isinstance(v, list) and v:
        return [str(x) for x in v if isinstance(x, str)]
    return [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ]


def default_deepseek_model() -> str:
    m = get_str("llm.deepseek.default_model").strip()
    if m:
        return m
    models = available_models_list()
    return models[0] if models else "deepseek-v4-flash"


def create_deepseek_chat_model(
    model: str | None = None,
    *,
    api_key: str | None = None,
) -> ChatOpenAI:
    if api_key is not None and api_key.strip():
        key = api_key.strip()
    else:
        key = get_str("llm.deepseek.api_key").strip()
    if not key:
        raise ValueError("未配置 DeepSeek API key：请在 settings.json 的 llm.deepseek.api_key 中填写密钥，或在界面中保存 DEEPSEEK_API_KEY。")

    return ChatOpenAI(
        model=(model or default_deepseek_model()).strip(),
        openai_api_key=key,
        openai_api_base=deepseek_base_url(),
        temperature=0,
    )
