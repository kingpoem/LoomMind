"""仓库根目录 `settings.json`：与 `template/settings.json` 深度合并，供全局配置读取。"""

import json
import shutil
from pathlib import Path
from typing import Any

_SETTINGS_FILENAME = "settings.json"
_TEMPLATE_DIRNAME = "template"

_settings_cache: dict[str, Any] | None = None

WIRE_LLM_KEYS_TO_JSON: dict[str, str] = {
    "OPENROUTER_API_KEY": "llm.openrouter.api_key",
    "OLLAMA_BASE_URL": "llm.ollama.base_url",
    "OLLAMA_API_KEY": "llm.ollama.api_key",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def settings_path() -> Path:
    return repo_root() / _SETTINGS_FILENAME


def template_settings_path() -> Path:
    return repo_root() / _TEMPLATE_DIRNAME / _SETTINGS_FILENAME


def ensure_settings_file() -> None:
    """首次本地运行时从 template/settings.json 复制到仓库根（目标已存在则跳过）。"""
    dest = settings_path()
    if dest.is_file():
        return
    src = template_settings_path()
    if src.is_file():
        shutil.copy2(src, dest)
        return
    dest.write_text("{}\n", encoding="utf-8")


def invalidate_settings_cache() -> None:
    global _settings_cache
    _settings_cache = None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _default_settings() -> dict[str, Any]:
    p = template_settings_path()
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _load_raw() -> dict[str, Any]:
    ensure_settings_file()
    defaults = _default_settings()
    user_path = settings_path()
    if not user_path.is_file():
        return defaults
    user_data = json.loads(user_path.read_text(encoding="utf-8"))
    return _deep_merge(defaults, user_data)


def get_settings_dict() -> dict[str, Any]:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = _load_raw()
    return _settings_cache


def get(path: str, default: Any = None) -> Any:
    d = get_settings_dict()
    cur: Any = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur if cur is not None else default


def get_str(path: str, default: str = "") -> str:
    v = get(path, default)
    if v is None:
        return default
    if isinstance(v, str):
        return v
    return str(v)


def require_str(path: str) -> str:
    v = get_str(path).strip()
    if not v:
        msg = f"缺少配置项 {path}（settings.json）"
        raise RuntimeError(msg)
    return v


def get_int(path: str, default: int) -> int:
    v = get(path)
    if v is None:
        return default
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return int(v.strip())
        except ValueError:
            return default
    return default


def get_optional_int(path: str) -> int | None:
    v = get(path)
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return int(v.strip())
        except ValueError:
            return None
    return None


def _deep_set(data: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    cur = data
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[keys[-1]] = value


def _deep_del(data: dict[str, Any], path: str) -> None:
    keys = path.split(".")
    cur = data
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            return
        cur = nxt
    cur.pop(keys[-1], None)


def merge_wire_llm_key(wire_key: str, value: str | None) -> None:
    """按 TUI 协议键名写入或清除嵌套字段。"""
    json_path = WIRE_LLM_KEYS_TO_JSON.get(wire_key)
    if json_path is None:
        msg = f"未知配置键：{wire_key!r}"
        raise ValueError(msg)
    ensure_settings_file()
    path = settings_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    if value is None or not value.strip():
        _deep_del(data, json_path)
    else:
        _deep_set(data, json_path, value.strip())
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    invalidate_settings_cache()


def merge_llm_provider(provider: str) -> None:
    """将 `llm.provider` 写入仓库根 settings.json（openrouter | ollama）。"""
    v = provider.strip().lower()
    if v not in ("openrouter", "ollama"):
        raise ValueError(f"无效 provider：{provider!r}")
    ensure_settings_file()
    path = settings_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    llm = data.get("llm")
    if not isinstance(llm, dict):
        llm = {}
        data["llm"] = llm
    llm["provider"] = v
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    invalidate_settings_cache()


def merge_trust_add_trusted_path(abs_path: Path | str) -> None:
    """将一条绝对路径加入 `trust.trusted_paths`（去重、排序后写回）。"""
    ensure_settings_file()
    path = settings_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    key = str(Path(abs_path).resolve())
    trust = data.setdefault("trust", {})
    if not isinstance(trust, dict):
        trust = {}
        data["trust"] = trust
    raw = trust.get("trusted_paths")
    items: list[str] = []
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, str) and x.strip():
                items.append(x.strip())
    if key not in items:
        items.append(key)
    trust["trusted_paths"] = sorted(set(items))
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    invalidate_settings_cache()
