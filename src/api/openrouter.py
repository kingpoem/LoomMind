# https://openrouter.ai/docs

import os

from langchain_openai import ChatOpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

AVAILABLE_MODELS: list[str] = [
    "deepseek/deepseek-chat",
    "deepseek/deepseek-chat-v3.1",
    "qwen/qwen3-30b-a3b",
]

DEFAULT_MODEL: str = AVAILABLE_MODELS[0]


def create_openrouter_chat_model(model: str | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=(model or DEFAULT_MODEL).strip(),
        openai_api_key=os.environ.get("OPENROUTER_API_KEY", "").strip(),
        openai_api_base=OPENROUTER_BASE_URL,
        temperature=0,
    )
