"""工作区目录浏览：等价于在工作区根下对子路径执行 `ls -hal` 与 `tree -L`。"""

import shutil
import subprocess

from mcp.server.fastmcp import FastMCP

from tools.list.files import _resolve_in_workspace
from trust import TrustCategory

_MAX_OUTPUT_BYTES = 256 * 1024  # 与 read_file 上限一致，避免巨量目录刷屏
_TREE_DEPTH_MIN = 1
_TREE_DEPTH_MAX = 32


def _truncate_output(text: str) -> str:
    raw = text or ""
    if len(raw.encode("utf-8", errors="replace")) <= _MAX_OUTPUT_BYTES:
        return raw
    # 按字符截断到约上限（UTF-8 安全）
    out = raw
    while len(out.encode("utf-8", errors="replace")) > _MAX_OUTPUT_BYTES:
        out = out[:-1]
    return out + "\n…（输出已截断）\n"


def register(mcp: FastMCP) -> dict[str, TrustCategory]:
    @mcp.tool()
    def workspace_ls(path: str = ".") -> str:
        """在工作区内对指定目录执行 `ls -hal`，查看权限、大小与条目列表。

        参数 path：相对工作区根的路径，或工作区内的绝对路径；`"."` 表示工作区根目录。
        拒绝工作区外的路径。输出过长时会截断。
        """
        resolved, err = _resolve_in_workspace(path)
        if err is not None or resolved is None:
            return f"workspace_ls 失败：{err}"
        if not resolved.exists():
            return f"workspace_ls 失败：路径不存在：{resolved}"
        if not resolved.is_dir():
            return f"workspace_ls 失败：不是目录：{resolved}"

        try:
            proc = subprocess.run(
                ["ls", "-hal", str(resolved)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return "workspace_ls 失败：命令超时"
        except OSError as ex:
            return f"workspace_ls 失败：{ex}"

        parts: list[str] = []
        if proc.stdout:
            parts.append(_truncate_output(proc.stdout.rstrip()))
        if proc.stderr:
            parts.append(f"stderr:\n{proc.stderr.rstrip()}")
        parts.append(f"exit_code: {proc.returncode}")
        return "\n\n".join(parts)

    @mcp.tool()
    def workspace_tree(path: str = ".", depth: int = 3) -> str:
        """在工作区内对指定目录执行 `tree -L <depth>`，查看目录树结构。

        参数 path：相对工作区根的路径，或工作区内的绝对路径；`"."` 表示工作区根。
        参数 depth：树深度，对应 `tree -L`（1–32）。输出过长时会截断。

        若系统未安装 `tree` 命令，会提示安装方式（如 macOS：`brew install tree`）。
        """
        resolved, err = _resolve_in_workspace(path)
        if err is not None or resolved is None:
            return f"workspace_tree 失败：{err}"
        if not resolved.exists():
            return f"workspace_tree 失败：路径不存在：{resolved}"
        if not resolved.is_dir():
            return f"workspace_tree 失败：不是目录：{resolved}"

        if depth < _TREE_DEPTH_MIN or depth > _TREE_DEPTH_MAX:
            lo, hi = _TREE_DEPTH_MIN, _TREE_DEPTH_MAX
            return f"workspace_tree 失败：depth 须在 {lo}–{hi} 之间"

        tree_bin = shutil.which("tree")
        if tree_bin is None:
            return "workspace_tree 失败：未找到 `tree` 可执行文件。macOS 可执行：`brew install tree`；或改用 run_cmd / find 等命令。"

        try:
            proc = subprocess.run(
                [tree_bin, "-L", str(int(depth)), str(resolved)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return "workspace_tree 失败：命令超时"
        except OSError as ex:
            return f"workspace_tree 失败：{ex}"

        parts: list[str] = []
        if proc.stdout:
            parts.append(_truncate_output(proc.stdout.rstrip()))
        if proc.stderr:
            parts.append(f"stderr:\n{proc.stderr.rstrip()}")
        parts.append(f"exit_code: {proc.returncode}")
        return "\n\n".join(parts)

    # 只读浏览，与 read_file 同为 READ_FS（信任工作区时可自动放行确认）
    return {
        "workspace_ls": TrustCategory.READ_FS,
        "workspace_tree": TrustCategory.READ_FS,
    }
