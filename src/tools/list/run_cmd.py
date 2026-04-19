"""run_cmd 工具：在系统命令行中执行命令并返回 stdout/stderr/exit_code。"""

import subprocess

from mcp.server.fastmcp import FastMCP

from trust import TrustCategory

_MAX_OUTPUT_BYTES = 256 * 1024
_TIMEOUT_SEC = 120


def _truncate_output(text: str) -> str:
    raw = text or ""
    if len(raw.encode("utf-8", errors="replace")) <= _MAX_OUTPUT_BYTES:
        return raw
    out = raw
    while len(out.encode("utf-8", errors="replace")) > _MAX_OUTPUT_BYTES:
        out = out[:-1]
    return out + "\n…（输出已截断）\n"


def register(mcp: FastMCP) -> dict[str, TrustCategory]:
    @mcp.tool()
    def run_cmd(command: str) -> str:
        """在本机命令行中执行命令，返回 stdout、stderr 和退出码。

        参数 command：要执行的完整命令字符串（纯文本）。
        Windows 下由 cmd.exe 解释（支持内置命令及管道）；
        Unix/macOS 下由 sh 解释（支持管道、重定向、通配符等 shell 特性）。
        命令以当前进程的权限在当前工作目录下执行。

        示例 command：
        - "ls -la /tmp"
        - "echo hello | wc -c"
        - "python --version"
        - "dir"（Windows）

        若需执行 Git 操作，优先使用 `git` 工具（不走 shell，命令参数经解析，更安全）。
        stderr 和非零退出码不会导致工具调用失败，会原样返回以便判断是否成功。
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            return "run_cmd 失败：命令超时"
        except OSError as ex:
            return f"run_cmd 失败：{ex}"

        parts = []
        if result.stdout:
            parts.append(f"stdout:\n{_truncate_output(result.stdout.rstrip())}")
        if result.stderr:
            parts.append(f"stderr:\n{_truncate_output(result.stderr.rstrip())}")
        parts.append(f"exit_code: {result.returncode}")
        return "\n\n".join(parts)

    return {"run_cmd": TrustCategory.EXEC}
