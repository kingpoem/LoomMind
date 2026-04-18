"""stdio：工具确认与调用通知（NDJSON）。"""

import json
import uuid

from tools.server import tool_category, tool_preview
from trust import TrustCategory

from .stdio_protocol import emit, read_command_line

_CATEGORY_HINTS: dict[TrustCategory, str] = {
    TrustCategory.READ_FS: "读取本地文件",
    TrustCategory.WRITE_FS: "写入本地文件",
    TrustCategory.EXEC: "执行系统命令",
    TrustCategory.NETWORK: "访问网络",
}


def _permissions_for(tool_name: str) -> list[str]:
    cat = tool_category(tool_name)
    if cat is None:
        return []
    hint = _CATEGORY_HINTS.get(cat)
    return [hint] if hint else []


def _preview_for(tool_name: str, args: dict) -> str | None:
    fn = tool_preview(tool_name)
    if fn is None:
        return None
    try:
        text = fn(args)
    except Exception:
        return None
    if not text or not isinstance(text, str):
        return None
    return text


def _safe_args(args: dict) -> dict:
    return json.loads(json.dumps(args, ensure_ascii=False, default=str))


def stdio_tool_confirm(tool_name: str, args: dict) -> bool:
    req_id = uuid.uuid4().hex
    safe_args = _safe_args(args)
    payload: dict = {
        "type": "tool_confirm_request",
        "id": req_id,
        "tool": tool_name,
        "args": safe_args,
        "permissions": _permissions_for(tool_name),
    }
    preview = _preview_for(tool_name, args)
    if preview is not None:
        payload["preview"] = preview
    emit(payload)
    while True:
        raw = read_command_line()
        if raw is None:
            return False
        if not raw:
            continue
        cmd = raw.get("type")
        if cmd == "tool_confirm_response" and raw.get("id") == req_id:
            return bool(raw.get("approved"))
        if cmd == "shutdown":
            return False


def stdio_tool_notify(tool_name: str, args: dict) -> None:
    emit(
        {
            "type": "tool_invoked",
            "tool": tool_name,
            "args": _safe_args(args),
        }
    )
