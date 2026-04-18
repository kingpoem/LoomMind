"""选模型后：根据 settings.json 决定还需配置项（供 TUI 列表 / 输入框）。"""

from api.provider import LLMProvider
from settings import get_str


def _settings_nonempty(key: str) -> bool:
    return bool(get_str(key).strip())


def collect_post_model_config_items(session) -> list[dict]:
    """返回 `{"id","label","hint"}` 列表；仅当 settings 中对应项为空时列入。"""
    p = session.llm.effective_provider()
    out: list[dict] = []
    if p is LLMProvider.OPENROUTER:
        if not _settings_nonempty("llm.openrouter.api_key"):
            out.append(
                {
                    "id": "OPENROUTER_API_KEY",
                    "label": "OpenRouter API 密钥",
                    "hint": "在 openrouter.ai 获取密钥；将写入项目根 settings.json",
                }
            )
    elif p is LLMProvider.OLLAMA:
        if not _settings_nonempty("llm.ollama.base_url"):
            out.append(
                {
                    "id": "OLLAMA_BASE_URL",
                    "label": "Ollama Base URL",
                    "hint": "例 http://127.0.0.1:11434 ；可带或不带 /v1",
                }
            )
        if not _settings_nonempty("llm.ollama.api_key"):
            out.append(
                {
                    "id": "OLLAMA_API_KEY",
                    "label": "Ollama API Key（占位）",
                    "hint": "本地一般填 ollama；将写入 settings.json",
                }
            )
    return out
