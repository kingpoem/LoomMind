"""stdio NDJSON 协议：仅 stdout 为事件流，调试与 traceback 走 stderr。"""

import json
import sys
from typing import Any

PROTOCOL_VERSION = 1


def emit(event: dict[str, Any]) -> None:
    """写一行 JSON 到 stdout。"""
    payload = dict(event)
    payload.setdefault("v", PROTOCOL_VERSION)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def read_command_line() -> dict[str, Any] | None:
    """从 stdin 读一行 JSON；EOF 返回 None。"""
    line = sys.stdin.readline()
    if line == "":
        return None
    line = line.strip()
    if not line:
        return {}
    return json.loads(line)
