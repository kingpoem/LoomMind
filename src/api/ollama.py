"""Ollama 本地模型"""

# https://github.com/ollama/ollama/blob/main/docs/openai.md

import json
import urllib.error
import urllib.request

from langchain_openai import ChatOpenAI

from settings import get_str


def _default_origin() -> str:
    return get_str("llm.ollama.default_origin", "http://127.0.0.1:11434").rstrip("/")


def _fallback_model() -> str:
    return get_str("llm.ollama.fallback_model", "llama3.2")


def normalized_openai_api_base(*, base_url_override: str | None = None) -> str:
    """供 ChatOpenAI 使用的 base，形如 http://host:11434/v1。"""
    raw = (base_url_override or "").strip().rstrip("/")
    if not raw:
        raw = get_str("llm.ollama.base_url").strip().rstrip("/")
    if not raw:
        raw = f"{_default_origin()}/v1"
    if not raw.lower().endswith("/v1"):
        raw = f"{raw}/v1"
    return raw


def _ollama_origin_for_tags(openai_api_base: str) -> str:
    b = openai_api_base.rstrip("/")
    if b.lower().endswith("/v1"):
        return b[:-3].rstrip("/")
    return b


def fetch_ollama_model_names(*, base_url_override: str | None = None, timeout: float = 3.0) -> list[str]:
    origin = _ollama_origin_for_tags(normalized_openai_api_base(base_url_override=base_url_override))
    url = f"{origin}/api/tags"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return []
    models = data.get("models") or []
    names: list[str] = []
    for m in models:
        n = m.get("name")
        if isinstance(n, str) and n.strip():
            names.append(n.strip())
    return names


def list_ollama_models(*, base_url_override: str | None = None) -> list[str]:
    names = fetch_ollama_model_names(base_url_override=base_url_override)
    extra = get_str("llm.ollama.model").strip()
    if extra and extra not in names:
        names.insert(0, extra)
    fb = _fallback_model()
    if not names:
        names = [extra or fb]
    return names


def default_ollama_model(*, base_url_override: str | None = None) -> str:
    explicit = get_str("llm.ollama.model").strip()
    if explicit:
        return explicit
    found = fetch_ollama_model_names(base_url_override=base_url_override)
    if found:
        return found[0]
    return _fallback_model()


def create_ollama_chat_model(
    model: str | None = None,
    *,
    base_url_override: str | None = None,
) -> ChatOpenAI:
    resolved = (model or default_ollama_model(base_url_override=base_url_override)).strip()
    # OpenAI 兼容客户端要求非空 key；本地 Ollama 不校验，占位即可
    placeholder = get_str("llm.ollama.api_key_placeholder", "ollama").strip()
    use_key = placeholder or "ollama"
    return ChatOpenAI(
        model=resolved,
        openai_api_key=use_key,
        openai_api_base=normalized_openai_api_base(base_url_override=base_url_override),
        temperature=0,
    )
