"""run_bash 工具：在 bash 中执行命令并返回 stdout/stderr/exit_code。"""

import subprocess

from mcp.server.fastmcp import FastMCP

from trust import TrustCategory


def register(mcp: FastMCP) -> dict[str, TrustCategory]:
    @mcp.tool()
    def run_bash(command: str) -> str:
        """在本机的 bash shell 中执行命令，返回 stdout、stderr 和退出码。

        参数 command：要执行的完整 bash 命令字符串（纯文本，不是 JSON），
        支持管道、重定向、通配符等 shell 特性。命令在当前主机上以当前进程的
        权限执行。

        示例 command：
        - "ls -la /tmp"
        - "uname -a"
        - "echo hello | wc -c"
        - "find . -name '*.py' | head -5"

        stderr 和非零退出码不会导致工具调用失败，但会原样返回以便判断命令是否成功。
        """
        result = subprocess.run(
            ["bash", "-c", "--", command],
            capture_output=True,
            text=True,
        )

        parts = []
        if result.stdout:
            parts.append(f"stdout:\n{result.stdout.rstrip()}")
        if result.stderr:
            parts.append(f"stderr:\n{result.stderr.rstrip()}")
        parts.append(f"exit_code: {result.returncode}")
        return "\n\n".join(parts)

    # EXEC 类别：信任态下也仍要人工确认。
    return {"run_bash": TrustCategory.EXEC}
