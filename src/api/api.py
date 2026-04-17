from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from .openrouter import (
    AVAILABLE_MODELS,
    DEFAULT_MODEL,
    create_openrouter_chat_model,
)


def create_chat_model(model: str | None = None) -> ChatOpenAI:
    return create_openrouter_chat_model(model=model)


def list_available_models() -> list[str]:
    return list(AVAILABLE_MODELS)


def default_model_name() -> str:
    return DEFAULT_MODEL


def invoke(messages: list[BaseMessage], model: str | None = None) -> BaseMessage:
    return create_chat_model(model=model).invoke(messages)
