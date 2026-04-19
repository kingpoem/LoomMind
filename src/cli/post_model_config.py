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
        # base_url 为空时回退到 llm.ollama.default_origin（template 默认本机 11434）
        if not _settings_nonempty("llm.ollama.base_url") and not get_str(
            "llm.ollama.default_origin"
        ).strip():
            out.append(
                {
                    "id": "OLLAMA_BASE_URL",
                    "label": "Ollama Base URL",
                    "hint": "例 http://127.0.0.1:11434（可带/不带 /v1）",
                }
            )
    return out
