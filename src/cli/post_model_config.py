"""选模型后列出仍缺的全局配置项（供 TUI）。"""

from api.provider import LLMProvider
from settings import get_str


def _settings_nonempty(key: str) -> bool:
    return bool(get_str(key).strip())


def collect_post_model_config_items(session) -> list[dict]:
    p = session.llm.effective_provider()
    out: list[dict] = []
    if p is LLMProvider.OPENROUTER:
        if not _settings_nonempty("llm.openrouter.api_key"):
            out.append(
                {
                    "id": "OPENROUTER_API_KEY",
                    "label": "OpenRouter API 密钥",
                    "hint": "openrouter.ai 创建；写入项目根 settings.json",
                }
            )
    elif p is LLMProvider.OLLAMA:
        if not _settings_nonempty("llm.ollama.base_url"):
            out.append(
                {
                    "id": "OLLAMA_BASE_URL",
                    "label": "Ollama Base URL",
                    "hint": "例 http://127.0.0.1:11434（可带/不带 /v1）",
                }
            )
        if not _settings_nonempty("llm.ollama.api_key"):
            out.append(
                {
                    "id": "OLLAMA_API_KEY",
                    "label": "Ollama API Key",
                    "hint": "按需填写（本地可填 ollama）",
                }
            )
    return out
