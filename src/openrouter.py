# https://openrouter.ai/docs

import os

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "deepseek/deepseek-chat"
# OPENROUTER_MODEL = "deepseek/deepseek-chat-v3.1"
# OPENROUTER_MODEL = "qwen/qwen3-30b-a3b"
# OPENROUTER_MODEL = "moonshotai/kimi-k2-0905-preview"


def openrouter_chat() -> ChatOpenAI:
    return ChatOpenAI(
        model=OPENROUTER_MODEL,
        openai_api_key=os.environ.get("OPENROUTER_API_KEY", "").strip(),
        openai_api_base=OPENROUTER_BASE_URL,
        temperature=0,
    )


def invoke_openrouter(messages: list[BaseMessage]) -> BaseMessage:
    return openrouter_chat().invoke(messages)
