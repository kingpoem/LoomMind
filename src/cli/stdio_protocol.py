"""stdio：一行一 JSON，事件走 stdout。"""

import json
import os
import sys
from typing import Any

PROTOCOL_VERSION = 1

_stdout_pipe_safe_installed = False


def _utf8_safe_str(s: str) -> str:
    """去掉无法用 UTF-8 单独编码的码位（如孤立 UTF-16 代理项），避免 json/管道编码抛错。"""
    return s.encode("utf-8", errors="replace").decode("utf-8")


def _sanitize_emit_value(obj: object) -> object:
    """递归净化 emit 负载中的字符串，保证 json.dumps 与下游编码安全。"""
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return _utf8_safe_str(obj)
    if isinstance(obj, dict):
        return {
            (_utf8_safe_str(k) if isinstance(k, str) else k): _sanitize_emit_value(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_sanitize_emit_value(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_emit_value(x) for x in obj)
    return _utf8_safe_str(str(obj))


def _write_fd1_utf8_line(text: str) -> None:
    """经文件描述符 1 写入 UTF-8 字节，绕过 TextIOWrapper。

    Windows 上子进程 stdout 为匿名管道时，`TextIOWrapper.write` 可能 OSError(22, EINVAL)。

    LLM/工具偶发返回非法 Unicode（如孤立的 UTF-16 代理项 \\udcaa），无法用标准 UTF-8 编码；
    写入前用 replace 替换为 U+FFFD，避免子进程因 encode 崩溃导致 TUI 断连。
    """
    data = text.encode("utf-8", errors="replace")
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
        if not isinstance(s, str):
            s = str(s)
        s = _utf8_safe_str(s)
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
    payload = _sanitize_emit_value(dict(event))
    assert isinstance(payload, dict)
    payload.setdefault("v", PROTOCOL_VERSION)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    _write_fd1_utf8_line(line)


def read_command_line() -> dict[str, Any] | None:
    # 须用二进制读再按 UTF-8 解码：Windows 上 TextIOWrapper 默认跟系统区域（如 cp936），
    # 而 TUI 子进程经管道写的是 UTF-8 字节，误解码会导致 JSON 里中文变成乱码。
    raw = sys.stdin.buffer.readline()
    if raw == b"":
        return None
    line = raw.decode("utf-8").strip()
    if not line:
        return {}
    return json.loads(line)
