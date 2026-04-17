"""stdio 模式下工具确认：经 stdout 请求 TUI，再从 stdin 读回应。"""

import json
import logging
import uuid
from collections.abc import Iterable

from .stdio_protocol import emit, read_command_line

logger = logging.getLogger(__name__)

_TOOL_PERMISSION_HINTS: dict[str, tuple[str, ...]] = {
    # run_bash 可直接访问本地文件系统，默认提示读写权限。
    "run_bash": ("local_file_read", "local_file_write"),
}


def _extract_permissions(tool_name: str, args: dict) -> list[str]:
    permissions: list[str] = []

    required = args.get("required_permissions")
    if isinstance(required, str):
        permissions.append(required)
    elif isinstance(required, Iterable):
        for item in required:
            if isinstance(item, str):
                permissions.append(item)

    permissions.extend(_TOOL_PERMISSION_HINTS.get(tool_name, ()))

    unique_permissions: list[str] = []
    seen: set[str] = set()
    for item in permissions:
        perm = item.strip()
        if not perm or perm in seen:
            continue
        seen.add(perm)
        unique_permissions.append(perm)
    return unique_permissions


def stdio_tool_confirm(tool_name: str, args: dict) -> bool:
    req_id = uuid.uuid4().hex
    safe_args = json.loads(json.dumps(args, default=str))
    permissions = _extract_permissions(tool_name, safe_args)
    emit(
        {
            "type": "tool_confirm_request",
            "id": req_id,
            "tool": tool_name,
            "args": safe_args,
            "permissions": permissions,
        }
    )
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
        logger.warning("等待工具确认时收到未处理指令: %s", cmd)
