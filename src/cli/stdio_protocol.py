"""stdio：一行一 JSON，事件走 stdout。"""

import json
import sys
from typing import Any

PROTOCOL_VERSION = 1


def emit(event: dict[str, Any]) -> None:
    payload = dict(event)
    payload.setdefault("v", PROTOCOL_VERSION)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def read_command_line() -> dict[str, Any] | None:
    line = sys.stdin.readline()
    if line == "":
        return None
    line = line.strip()
    if not line:
        return {}
    return json.loads(line)
