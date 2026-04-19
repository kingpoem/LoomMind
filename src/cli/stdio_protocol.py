"""stdio：一行一 JSON，事件走 stdout。"""

import json
import os
import sys
from typing import Any

PROTOCOL_VERSION = 1

_stdout_pipe_safe_installed = False


def _write_fd1_utf8_line(text: str) -> None:
    """经文件描述符 1 写入 UTF-8 字节，绕过 TextIOWrapper。

    Windows 上子进程 stdout 为匿名管道时，`TextIOWrapper.write` 可能 OSError(22, EINVAL)。
    """
    data = text.encode("utf-8")
    mv = memoryview(data)
    while len(mv):
        try:
            n = os.write(1, mv)
        except OSError:
            return
        if n <= 0:
            return
        mv = mv[n:]


class _PipeSafeStdout:
    """第三方仍写 sys.stdout 时吞 OSError；协议输出走 os.write(1)。"""

    __slots__ = ("_inner",)

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def write(self, s: str) -> int:
        try:
            return self._inner.write(s)
        except OSError:
            return 0

    def flush(self) -> None:
        try:
            self._inner.flush()
        except OSError:
            pass

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def install_pipe_safe_stdout() -> None:
    global _stdout_pipe_safe_installed
    if _stdout_pipe_safe_installed:
        return
    sys.stdout = _PipeSafeStdout(sys.stdout)
    _stdout_pipe_safe_installed = True


def emit(event: dict[str, Any]) -> None:
    payload = dict(event)
    payload.setdefault("v", PROTOCOL_VERSION)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    _write_fd1_utf8_line(line)


def read_command_line() -> dict[str, Any] | None:
    line = sys.stdin.readline()
    if line == "":
        return None
    line = line.strip()
    if not line:
        return {}
    return json.loads(line)
