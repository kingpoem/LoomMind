"""stdio 模式下工作区信任询问：经 stdout 发请求，再从 stdin 读回应。

结构与 stdio_confirm.py 一致，但信任询问只发生一次（启动时），
不挂 request id；用 `shutdown` 提前退出也按拒绝处理。
"""

import logging
from pathlib import Path

from .stdio_protocol import emit, read_command_line

logger = logging.getLogger(__name__)


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
        logger.warning("等待工作区信任应答时收到未处理指令: %s", cmd)
