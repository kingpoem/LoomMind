"""stdio：启动时工作区信任询问（stdout 请求 / stdin 回应）。"""

from pathlib import Path

from .stdio_protocol import emit, read_command_line


def stdio_trust_prompt(workspace: Path) -> bool:
    emit({"type": "trust_request", "workspace": str(workspace)})
    while True:
        raw = read_command_line()
        if raw is None:
            return False
        if not raw:
            continue
        cmd = raw.get("type")
        if cmd == "trust_response":
            return bool(raw.get("trust"))
        if cmd in ("shutdown", "quit", "exit"):
            return False
