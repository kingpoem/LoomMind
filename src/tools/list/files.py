"""文件类工具：read_file / edit_file / write_file。

边界：三者都只在工作区内操作。即便用户同意，也拒绝触达外部路径——
启动期的信任模态语义是"信任工作区"，per-call 同意是 flow-state 操作，
路径越界的风险不该让用户每次细审。如需更宽的访问面，请以更高 CWD
起会话。
"""

import difflib
import logging
import os
import shutil
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from tools.server import ToolSpec
from trust import TrustCategory, workspace_root

logger = logging.getLogger(__name__)

_MAX_READ_BYTES = 256 * 1024  # 256 KiB，避免一次性吞入超大文件
_PREVIEW_MAX_LINES = 40  # 预览 diff 超过此行数则截断
_PREVIEW_NEW_CONTENT_LINES = 20  # 新建预览最多展示前若干行


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


def _atomic_write_text(target: Path, text: str) -> None:
    """把文本原子写入 target：先写同目录临时文件，再 os.replace 覆盖。

    同目录可保证 replace 在同一文件系统上是原子的；同时：
    - 覆盖已存在文件时，`shutil.copystat` 回填权限/时间戳，避免丢失 mode；
    - 创建新文件时，tempfile 默认 0600；这里按当前 umask 调成 0666&~umask，
      与 `open(path, 'w')` 的默认观感一致。
    """
    directory = target.parent
    target_existed = target.exists()
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=directory,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    if target_existed:
        try:
            shutil.copystat(target, tmp_path)
        except OSError:
            # 权限拷贝失败不影响正确性，只是少了 mode 保持；继续 replace。
            logger.debug("copystat 失败：%s -> %s", target, tmp_path)
    else:
        try:
            current_umask = os.umask(0)
            os.umask(current_umask)
            os.chmod(tmp_path, 0o666 & ~current_umask)
        except OSError:
            logger.debug("默认模式 chmod 失败：%s", tmp_path)
    os.replace(tmp_path, target)


def _simulate_edit(
    content: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
) -> tuple[str | None, int, str | None]:
    """在内存里模拟替换；返回 (新内容, 替换次数, 失败原因)。

    规则与 `edit_file` 对外行为完全一致，抽成纯函数便于 `_preview_edit`
    与工具主体共用——免得预览和真实执行判定漂移。
    """
    if not old_string:
        return None, 0, "old_string 不能为空"
    if old_string == new_string:
        return None, 0, "old_string 与 new_string 相同，无需替换"
    count = content.count(old_string)
    if count == 0:
        return None, 0, "未在文件中找到 old_string（注意空格、缩进、引号等细节）"
    if not replace_all and count > 1:
        return (
            None,
            count,
            f"匹配到 {count} 处，请补充上下文使 old_string 唯一，"
            "或传入 replace_all=True",
        )
    if replace_all:
        new_content = content.replace(old_string, new_string)
    else:
        new_content = content.replace(old_string, new_string, 1)
    return new_content, count, None


def _read_text_for_edit(resolved: Path) -> tuple[str | None, str | None]:
    """读取用于编辑的文本内容；失败时返回 (None, 原因)。"""
    if not resolved.exists():
        return None, f"文件不存在：{resolved}（如需创建或覆写，请改用 write_file）"
    if resolved.is_dir():
        return None, f"路径是目录，不是文件：{resolved}"
    if not resolved.is_file():
        return None, f"不是常规文件：{resolved}"
    try:
        return resolved.read_text(encoding="utf-8", errors="replace"), None
    except OSError as err:
        return None, f"读取失败：{err}"


def _format_diff(before: str, after: str, display_path: str) -> str:
    """生成截断后的 unified diff 字符串。"""
    lines = list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=display_path,
            tofile=display_path,
            n=3,
        )
    )
    # unified_diff 行末通常已带 \n；拼合后再按需截断。
    if len(lines) > _PREVIEW_MAX_LINES:
        head = "".join(lines[:_PREVIEW_MAX_LINES])
        remaining = len(lines) - _PREVIEW_MAX_LINES
        if not head.endswith("\n"):
            head += "\n"
        return head + f"…（diff 已截断，另有 {remaining} 行）\n"
    return "".join(lines)


def _format_new_file_preview(display: str, content: str) -> str:
    """创建新文件时，展示前若干行（以 `+ ` 前缀模仿 diff 插入）。"""
    lines = content.splitlines()
    header = f"将创建新文件（{display}，{len(content)} 字节 / {len(lines)} 行）\n"
    if not lines:
        return header + "（空文件）\n"
    shown = lines[:_PREVIEW_NEW_CONTENT_LINES]
    body = "\n".join(f"+ {line}" for line in shown)
    if len(lines) > _PREVIEW_NEW_CONTENT_LINES:
        remaining = len(lines) - _PREVIEW_NEW_CONTENT_LINES
        body += f"\n…（另有 {remaining} 行未展示）"
    return header + body + "\n"


def _preview_edit(args: dict) -> str | None:
    """为 edit_file 生成 diff 预览字符串；任何异常都吞掉返回 None。"""
    try:
        path = args.get("path")
        old_string = args.get("old_string")
        new_string = args.get("new_string")
        replace_all = bool(args.get("replace_all", False))
        if (
            not isinstance(path, str)
            or not isinstance(old_string, str)
            or not isinstance(new_string, str)
        ):
            return None

        resolved, err = _resolve_in_workspace(path)
        if err is not None or resolved is None:
            return f"预览失败：{err}"

        content, err = _read_text_for_edit(resolved)
        if err is not None or content is None:
            return f"预览失败：{err}"

        new_content, count, err = _simulate_edit(
            content, old_string, new_string, replace_all
        )
        if err is not None or new_content is None:
            return f"预览失败：{err}"

        root = workspace_root()
        try:
            display = str(resolved.relative_to(root))
        except ValueError:
            display = str(resolved)
        diff = _format_diff(content, new_content, display)
        header = f"将替换 {count} 处（{display}）\n"
        if not diff:
            return header + "（diff 为空——内容未变化？）"
        return header + diff
    except Exception:
        logger.exception("edit_file 预览生成失败")
        return None


def _preview_write(args: dict) -> str | None:
    """为 write_file 生成预览：覆盖→diff，新建→前若干行。异常一律吞为 None。"""
    try:
        path = args.get("path")
        content = args.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            return None

        resolved, err = _resolve_in_workspace(path)
        if err is not None or resolved is None:
            return f"预览失败：{err}"

        root = workspace_root()
        try:
            display = str(resolved.relative_to(root))
        except ValueError:
            display = str(resolved)

        if resolved.exists():
            if resolved.is_dir():
                return f"预览失败：路径是目录：{display}"
            if not resolved.is_file():
                return f"预览失败：不是常规文件：{display}"
            try:
                old = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError as err_read:
                return f"预览失败：读取失败：{err_read}"
            if old == content:
                return f"内容未变化（{display}，{len(content)} 字节）"
            header = (
                f"将覆盖（{display}，原 {len(old)} 字节 / "
                f"{len(old.splitlines())} 行 → 新 {len(content)} 字节 / "
                f"{len(content.splitlines())} 行）\n"
            )
            return header + _format_diff(old, content, display)

        return _format_new_file_preview(display, content)
    except Exception:
        logger.exception("write_file 预览生成失败")
        return None


def register(mcp: FastMCP) -> dict[str, TrustCategory | ToolSpec]:
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

    @mcp.tool()
    def edit_file(
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str:
        """在工作区内某个已存在的文件里，把 old_string 替换为 new_string。

        参数：
        - path：文件路径（绝对或相对工作区根）。**仅支持工作区内部。**
        - old_string：要被替换的原文，必须与文件内容精确匹配（含空白、缩进）。
        - new_string：替换后的文本。不得与 old_string 相同。
        - replace_all：默认 False，此时 old_string 必须在文件中**唯一出现**，
          否则工具会要求你补充上下文。传 True 时替换所有匹配并汇报次数。

        不会创建新文件——若文件不存在会直接报错（后续 write_file 负责创建/覆写）。
        写入是原子的（临时文件 + os.replace），权限/mtime 通过 copystat 保留。

        失败时返回以「edit_file 失败：」开头的诊断串，便于你据此调整参数重试。
        """
        resolved, err = _resolve_in_workspace(path)
        if err is not None or resolved is None:
            return f"edit_file 失败：{err}"

        content, err = _read_text_for_edit(resolved)
        if err is not None or content is None:
            return f"edit_file 失败：{err}"

        new_content, count, err = _simulate_edit(
            content, old_string, new_string, replace_all
        )
        if err is not None or new_content is None:
            return f"edit_file 失败：{err}"

        try:
            _atomic_write_text(resolved, new_content)
        except OSError as err_write:
            return f"edit_file 失败：写入失败：{err_write}"

        return f"edit_file OK: 替换 {count} 处（{resolved}）"

    @mcp.tool()
    def write_file(path: str, content: str) -> str:
        """创建新文件或覆盖已存在的文件。**仅支持工作区内部。**

        参数：
        - path：目标文件路径（绝对或相对工作区根）。若父目录不存在会自动在
          工作区内创建。
        - content：要写入的完整文本内容（UTF-8）。可为空串（写出空文件）。

        与 edit_file 的分工：
        - 创建新文件，或手上已有完整新内容要覆写已存在文件 → write_file。
        - 只想在既有文件里改几行局部片段 → edit_file（让用户看的 diff 更小更直观）。

        写入原子化：临时文件 + os.replace；覆盖时 copystat 保留原权限/mtime，
        新建时按当前 umask 调整为 0666&~umask（与普通 open('w') 一致）。

        用户会在确认模态里看到 diff（覆盖）或前若干行（新建）。按 [允许] 才会
        真正落盘。
        """
        resolved, err = _resolve_in_workspace(path)
        if err is not None or resolved is None:
            return f"write_file 失败：{err}"

        if resolved.exists():
            if resolved.is_dir():
                return f"write_file 失败：路径是目录：{resolved}"
            if not resolved.is_file():
                return f"write_file 失败：不是常规文件：{resolved}"

        parent = resolved.parent
        if parent.exists() and not parent.is_dir():
            return f"write_file 失败：父路径不是目录：{parent}"
        if not parent.exists():
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as err_mk:
                return f"write_file 失败：无法创建父目录：{err_mk}"

        is_new = not resolved.exists()
        try:
            _atomic_write_text(resolved, content)
        except OSError as err_write:
            return f"write_file 失败：写入失败：{err_write}"

        verb = "创建" if is_new else "覆盖"
        return f"write_file OK: {verb} {resolved}（{len(content)} 字节）"

    # read_file: READ_FS（信任态自动放行）
    # edit_file / write_file: WRITE_FS（始终需要确认），附带预览
    return {
        "read_file": TrustCategory.READ_FS,
        "edit_file": ToolSpec(TrustCategory.WRITE_FS, preview=_preview_edit),
        "write_file": ToolSpec(TrustCategory.WRITE_FS, preview=_preview_write),
    }
