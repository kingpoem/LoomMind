"""文件类工具：目前提供 read_file，仅允许读取工作区内的文件。"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from trust import TrustCategory, workspace_root

_MAX_READ_BYTES = 256 * 1024  # 256 KiB，避免一次性吞入超大文件


def _resolve_in_workspace(raw_path: str) -> tuple[Path | None, str | None]:
    """把输入路径解析为工作区内的绝对路径；越界或格式错误返回 (None, 错误原因)。

    - 绝对路径按原样处理；相对路径视作相对工作区根目录（而非进程 CWD）。
    - `resolve(strict=False)` 会展开符号链接：工作区内指向外部的 symlink
      将按真实位置判定，从而被拒绝——这正是「仅信任工作区」的应有行为。
    """
    root = workspace_root()
    if not raw_path or not raw_path.strip():
        return None, "path 不能为空"
    p = Path(raw_path.strip())
    if not p.is_absolute():
        p = root / p
    try:
        resolved = p.resolve(strict=False)
    except OSError as err:
        return None, f"路径解析失败：{err}"
    if not resolved.is_relative_to(root):
        return None, f"拒绝访问工作区之外的路径：{resolved}（工作区={root}）"
    return resolved, None


def register(mcp: FastMCP) -> dict[str, TrustCategory]:
    @mcp.tool()
    def read_file(path: str) -> str:
        """读取工作区内某个文件的文本内容。

        参数 path：文件路径。可以是绝对路径，也可以是相对工作区根目录的相对路径。
        拒绝读取工作区之外的任何文件（符号链接按解析后的真实位置判定）。
        读取上限为 256 KiB；更大的文件会被拒绝并提示使用 run_bash 中的
        head/tail/sed 等命令分片读取。返回文件原样文本内容。

        示例 path：
        - "src/main.py"
        - "memory/MEMORY.md"
        - "/home/user/proj/README.md"  # 必须位于工作区内
        """
        resolved, err = _resolve_in_workspace(path)
        if err is not None or resolved is None:
            return f"read_file 失败：{err}"
        if not resolved.exists():
            return f"read_file 失败：文件不存在：{resolved}"
        if resolved.is_dir():
            return f"read_file 失败：路径是目录，不是文件：{resolved}"
        if not resolved.is_file():
            return f"read_file 失败：不是常规文件：{resolved}"
        try:
            size = resolved.stat().st_size
        except OSError as err_stat:
            return f"read_file 失败：无法获取文件状态：{err_stat}"
        if size > _MAX_READ_BYTES:
            return (
                f"read_file 失败：文件过大（{size} 字节，上限 "
                f"{_MAX_READ_BYTES} 字节）。请通过 run_bash 使用 "
                "head/tail/sed 等命令分片读取。"
            )
        try:
            return resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as err_read:
            return f"read_file 失败：{err_read}"

    # READ_FS 类别：信任态下自动放行；未信任时仍需人工确认。
    return {"read_file": TrustCategory.READ_FS}
