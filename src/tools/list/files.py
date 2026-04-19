"""文件类工具：read_file / edit_file / write_file / create_file / delete_file /
apply_file_patch。

边界：均只在工作区内操作。即便用户同意，也拒绝触达外部路径——
启动期的信任模态语义是"信任工作区"，per-call 同意是 flow-state 操作，
路径越界的风险不该让用户每次细审。如需更宽的访问面，请以更高 CWD
起会话。
"""

import difflib
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from tools.server import ToolSpec
from trust import TrustCategory, workspace_root

logger = logging.getLogger(__name__)

_MAX_READ_BYTES = 256 * 1024  # 256 KiB，避免一次性吞入超大文件
_PREVIEW_MAX_LINES = 40  # 预览 diff 超过此行数则截断
_PREVIEW_NEW_CONTENT_LINES = 20  # 新建预览最多展示前若干行

_PATCH_BEGIN = "*** Begin Patch"
_PATCH_END = "*** End Patch"
_RE_ADD = re.compile(r"^\s*\*\*\*\s+Add File:\s*(.+?)\s*$")
_RE_UPDATE = re.compile(r"^\s*\*\*\*\s+Update File:\s*(.+?)\s*$")
_RE_DELETE = re.compile(r"^\s*\*\*\*\s+Delete File:")
_RE_MOVE = re.compile(r"^\s*\*\*\*\s+Move to:")


@dataclass(frozen=True)
class _ParsedAdd:
    path: str
    content: str


@dataclass(frozen=True)
class _ParsedUpdate:
    path: str
    hunks: list[tuple[list[str], list[str]]]


def _normalize_patch_text(patch: str) -> str:
    return patch.replace("\r\n", "\n").replace("\r", "\n")


def _extract_patch_envelope(patch: str) -> tuple[list[str] | None, str | None]:
    """返回信封内行列表（不含 Begin/End 行），失败时 (None, 原因)。"""
    text = _normalize_patch_text(patch)
    lines = text.split("\n")
    start_i: int | None = None
    end_i: int | None = None
    for i, ln in enumerate(lines):
        if ln.strip() == _PATCH_BEGIN:
            start_i = i
            break
    if start_i is None:
        return None, f"缺少 {_PATCH_BEGIN}"
    for j in range(start_i + 1, len(lines)):
        if lines[j].strip() == _PATCH_END:
            end_i = j
            break
    if end_i is None:
        return None, f"缺少 {_PATCH_END}"
    inner = lines[start_i + 1 : end_i]
    for ln in inner:
        if ln.strip() == _PATCH_BEGIN:
            return None, "仅允许单段 patch（出现嵌套的 Begin）"
    return inner, None


def _parse_hunk_segment(seg: list[str]) -> tuple[list[str], list[str]]:
    """单段内先全部 - 行再全部 + 行；允许仅 - 或仅 +（插入/删除）。"""
    minus: list[str] = []
    plus: list[str] = []
    seen_plus = False
    for raw in seg:
        ln = raw.rstrip("\r")
        if not ln.strip():
            continue
        if ln.startswith("@@"):
            raise ValueError("@@ 只能作为分段边界出现在段首，请检查格式")
        if ln.startswith("-"):
            if seen_plus:
                raise ValueError("同一段内 `-` 不能出现在 `+` 之后；请用 @@ 分段")
            minus.append(ln[1:])
        elif ln.startswith("+"):
            seen_plus = True
            plus.append(ln[1:])
        else:
            raise ValueError(f"无效行（须以 - 或 + 开头）：{ln!r}")
    return minus, plus


def _split_update_segments(body_lines: list[str]) -> list[list[str]]:
    """按 @@ 切分为多段；无 @@ 时整段 body 为一段。"""
    lines = [ln.rstrip("\r") for ln in body_lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return []
    has_at = any(ln.startswith("@@") for ln in lines)
    if not has_at:
        return [lines]
    segments: list[list[str]] = []
    buf: list[str] = []
    for ln in lines:
        if ln.startswith("@@"):
            if buf:
                segments.append(buf)
                buf = []
        else:
            buf.append(ln)
    if buf:
        segments.append(buf)
    return segments


def _parse_single_file_patch(
    patch: str,
) -> tuple[_ParsedAdd | _ParsedUpdate | None, str | None]:
    """解析单文件子集；成功返回 (Parsed, None)，失败返回 (None, 原因)。"""
    inner, err = _extract_patch_envelope(patch)
    if err is not None or inner is None:
        return None, err

    add_line: int | None = None
    update_line: int | None = None
    raw_path_add: str | None = None
    raw_path_update: str | None = None

    for i, ln in enumerate(inner):
        if _RE_DELETE.match(ln):
            return None, "不支持 *** Delete File（请拆成单独工具调用或使用其他方式）"
        if _RE_MOVE.match(ln):
            return None, "不支持 *** Move to（请用 Update 或多次工具调用）"
        m_add = _RE_ADD.match(ln)
        if m_add:
            if add_line is not None:
                return None, "仅允许一个 *** Add File 节"
            add_line = i
            raw_path_add = m_add.group(1).strip()
            continue
        m_up = _RE_UPDATE.match(ln)
        if m_up:
            if update_line is not None:
                return None, "仅允许一个 *** Update File 节"
            update_line = i
            raw_path_update = m_up.group(1).strip()
            continue

    if (add_line is None) == (update_line is None):
        if add_line is not None and update_line is not None:
            return None, "不能同时包含 *** Add File 与 *** Update File"
        return None, "须恰好包含一个 *** Add File 或一个 *** Update File 节"

    if add_line is not None:
        for j, ln in enumerate(inner):
            if j <= add_line:
                continue
            if ln.strip().startswith("***"):
                return None, f"Add File 之后出现意外的节：{ln.strip()!r}"
        body = inner[add_line + 1 :]
        parts: list[str] = []
        for ln in body:
            if not ln.strip():
                return None, "Add File 正文中不允许空行（空行请使用单独一行 `+`）"
            if not ln.startswith("+"):
                return None, f"Add File 正文每行须以 + 开头：{ln!r}"
            parts.append(ln[1:])
        content = "\n".join(parts)
        assert raw_path_add is not None
        return _ParsedAdd(path=raw_path_add, content=content), None

    assert update_line is not None and raw_path_update is not None
    body_lines = inner[update_line + 1 :]
    for ln in body_lines:
        if ln.strip().startswith("***"):
            return None, f"Update File 之后出现意外的节：{ln.strip()!r}"

    segs = _split_update_segments(body_lines)
    if not segs:
        return None, "Update File 缺少有效正文（需要至少一段 - / + 变更）"

    hunks: list[tuple[list[str], list[str]]] = []
    try:
        for seg in segs:
            hunks.append(_parse_hunk_segment(seg))
    except ValueError as ex:
        return None, str(ex)

    if not any(m or p for m, p in hunks):
        return None, "没有可应用的变更（每段至少一行 - 或 +）"

    return _ParsedUpdate(path=raw_path_update, hunks=hunks), None


def _apply_replace_first(content: str, old_string: str, new_string: str) -> tuple[str | None, str | None]:
    """替换第一处；多处匹配则失败。"""
    if old_string == new_string:
        return content, None
    count = content.count(old_string)
    if count == 0:
        return None, "未在文件中找到与 `-` 块匹配的原文（注意换行与空格）"
    if count > 1:
        return (
            None,
            f"匹配到 {count} 处，请补充上下文或拆成多段（用 @@ 分段）使每处唯一",
        )
    return content.replace(old_string, new_string, 1), None


def _apply_update_hunks(content: str, hunks: list[tuple[list[str], list[str]]]) -> tuple[str | None, str | None]:
    out = content
    for idx, (minus, plus) in enumerate(hunks):
        old_text = "\n".join(minus)
        new_text = "\n".join(plus)
        if old_text == "" and new_text == "":
            return None, f"第 {idx + 1} 段：`-` 与 `+` 均为空"
        if old_text == "":
            if not new_text:
                continue
            if not out:
                out = new_text
            else:
                out = new_text + "\n" + out
            continue
        replaced, err = _apply_replace_first(out, old_text, new_text)
        if err is not None:
            return None, f"第 {idx + 1} 段：{err}"
        assert replaced is not None
        out = replaced
    return out, None


def _simulate_apply_file_patch(
    patch: str, explicit_path: str | None
) -> tuple[_ParsedAdd | _ParsedUpdate | None, Path | None, str | None, str | None]:
    """返回 (parsed, resolved_path, before_text_or_none, error)。

    Add 时 before 为 None；Update 时 before 为读取内容。
    """
    parsed, perr = _parse_single_file_patch(patch)
    if perr is not None or parsed is None:
        return None, None, None, perr

    raw_path = parsed.path
    resolved, err = _resolve_in_workspace(raw_path)
    if err is not None or resolved is None:
        return None, None, None, err

    if explicit_path is not None and explicit_path.strip():
        exp_res, eerr = _resolve_in_workspace(explicit_path.strip())
        if eerr is not None or exp_res is None:
            return None, None, None, f"path 参数无效：{eerr}"
        if exp_res != resolved:
            return (
                None,
                None,
                None,
                f"path 参数与 patch 内路径不一致：{exp_res} ≠ {resolved}",
            )

    if isinstance(parsed, _ParsedAdd):
        if resolved.exists():
            return (
                None,
                None,
                None,
                f"文件已存在：{resolved}（Add 仅用于新建；覆盖请用 write_file 或 Update）",
            )
        return parsed, resolved, None, None

    try:
        size = resolved.stat().st_size
    except OSError as err_sz:
        return None, None, None, f"无法获取文件大小：{err_sz}"
    if size > _MAX_READ_BYTES:
        return (
            None,
            None,
            None,
            f"文件过大（{size} 字节，上限 {_MAX_READ_BYTES} 字节）",
        )

    content, rerr = _read_text_for_edit(resolved)
    if rerr is not None or content is None:
        return None, None, None, rerr
    new_content, aerr = _apply_update_hunks(content, parsed.hunks)
    if aerr is not None or new_content is None:
        return None, None, None, aerr
    if new_content == content:
        return None, None, None, "应用后内容与原文相同，无需写入"
    return parsed, resolved, content, None


def _display_rel(resolved: Path) -> str:
    root = workspace_root()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def _preview_apply_file_patch(args: dict) -> str | None:
    try:
        patch = args.get("patch")
        explicit = args.get("path")
        if not isinstance(patch, str):
            return None
        if explicit is not None and not isinstance(explicit, str):
            return None

        parsed, resolved, before, err = _simulate_apply_file_patch(patch, explicit)
        if err is not None:
            return f"预览失败：{err}"
        if parsed is None or resolved is None:
            return None

        display = _display_rel(resolved)
        if isinstance(parsed, _ParsedAdd):
            return _format_new_file_preview(display, parsed.content)

        assert before is not None
        new_content, aerr = _apply_update_hunks(before, parsed.hunks)
        if aerr is not None or new_content is None:
            return f"预览失败：{aerr}"
        diff = _format_diff(before, new_content, display)
        header = f"apply_file_patch（Update {display}）\n"
        return header + diff if diff else header + "（无 diff）\n"
    except Exception:
        logger.exception("apply_file_patch 预览生成失败")
        return None


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
            f"匹配到 {count} 处，请补充上下文使 old_string 唯一，或传入 replace_all=True",
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
        if not isinstance(path, str) or not isinstance(old_string, str) or not isinstance(new_string, str):
            return None

        resolved, err = _resolve_in_workspace(path)
        if err is not None or resolved is None:
            return f"预览失败：{err}"

        content, err = _read_text_for_edit(resolved)
        if err is not None or content is None:
            return f"预览失败：{err}"

        new_content, count, err = _simulate_edit(content, old_string, new_string, replace_all)
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
                f"将覆盖（{display}，原 {len(old)} 字节 / {len(old.splitlines())} 行 → 新 {len(content)} 字节 / {len(content.splitlines())} 行）\n"
            )
            return header + _format_diff(old, content, display)

        return _format_new_file_preview(display, content)
    except Exception:
        logger.exception("write_file 预览生成失败")
        return None


def _preview_create_file(args: dict) -> str | None:
    """为 create_file 生成预览；已存在路径则失败说明。"""
    try:
        path = args.get("path")
        content = args.get("content")
        if not isinstance(path, str):
            return None
        if content is None:
            content = ""
        if not isinstance(content, str):
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
            return f"预览失败：路径已存在：{display}（create_file 仅用于新建；覆盖请用 write_file）"
        return _format_new_file_preview(display, content)
    except Exception:
        logger.exception("create_file 预览生成失败")
        return None


def _preview_delete_file(args: dict) -> str | None:
    """为 delete_file 生成预览：路径、大小与文件开头若干行。"""
    try:
        path = args.get("path")
        if not isinstance(path, str):
            return None

        resolved, err = _resolve_in_workspace(path)
        if err is not None or resolved is None:
            return f"预览失败：{err}"

        root = workspace_root()
        try:
            display = str(resolved.relative_to(root))
        except ValueError:
            display = str(resolved)

        if not resolved.exists():
            return f"预览失败：文件不存在：{display}"
        if resolved.is_dir():
            return f"预览失败：路径是目录（delete_file 只删除普通文件）：{display}"
        if not resolved.is_file():
            return f"预览失败：不是常规文件：{display}"

        try:
            size = resolved.stat().st_size
        except OSError as err_stat:
            return f"预览失败：无法获取文件状态：{err_stat}"

        header = f"将永久删除文件（{display}，{size} 字节）\n"
        if size == 0:
            return header + "（空文件）\n"
        if size > _MAX_READ_BYTES:
            return header + f"（过大，不展示内容预览；上限 {_MAX_READ_BYTES} 字节）\n"
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as err_read:
            return f"预览失败：读取失败：{err_read}"
        lines = text.splitlines()
        shown = lines[:_PREVIEW_NEW_CONTENT_LINES]
        body = "\n".join(f"  {line}" for line in shown)
        extra = len(lines) - len(shown)
        if extra > 0:
            body += f"\n  …（另有 {extra} 行未展示）"
        return header + "内容预览：\n" + body + "\n"
    except Exception:
        logger.exception("delete_file 预览生成失败")
        return None


def register(mcp: FastMCP) -> dict[str, TrustCategory | ToolSpec]:
    @mcp.tool()
    def read_file(path: str) -> str:
        """读取工作区内某个文件的文本内容。

        参数 path：文件路径。可以是绝对路径，也可以是相对工作区根目录的相对路径。
        拒绝读取工作区之外的任何文件（符号链接按解析后的真实位置判定）。
        读取上限为 256 KiB；更大的文件会被拒绝并提示使用 run_cmd 中的
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
            return f"read_file 失败：文件过大（{size} 字节，上限 {_MAX_READ_BYTES} 字节）。请通过 run_cmd 使用 head/tail/sed 等命令分片读取。"
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

        new_content, count, err = _simulate_edit(content, old_string, new_string, replace_all)
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

    @mcp.tool()
    def create_file(path: str, content: str = "") -> str:
        """在工作区内**仅当目标不存在时**创建新文件；已存在则报错不覆盖。

        参数 path、content 与 write_file 相同（UTF-8 文本；content 默认空串即空文件）。
        父目录不存在时会自动创建。原子写入方式与 write_file 一致。

        需要覆盖或更新已有文件请用 write_file / edit_file / apply_file_patch。
        """
        resolved, err = _resolve_in_workspace(path)
        if err is not None or resolved is None:
            return f"create_file 失败：{err}"

        if resolved.exists():
            if resolved.is_dir():
                return f"create_file 失败：路径是已存在的目录：{resolved}"
            if resolved.is_file():
                return f"create_file 失败：文件已存在：{resolved}（请改用 write_file 覆盖或先 delete_file）"
            return f"create_file 失败：路径已存在且不是可写文件：{resolved}"

        parent = resolved.parent
        if parent.exists() and not parent.is_dir():
            return f"create_file 失败：父路径不是目录：{parent}"
        if not parent.exists():
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as err_mk:
                return f"create_file 失败：无法创建父目录：{err_mk}"

        try:
            _atomic_write_text(resolved, content)
        except OSError as err_write:
            return f"create_file 失败：写入失败：{err_write}"

        return f"create_file OK: {resolved}（{len(content)} 字节）"

    @mcp.tool()
    def delete_file(path: str) -> str:
        """删除工作区内的单个普通文件（非目录）。**仅工作区内部路径。**

        符号链接若解析到工作区内的常规文件则删除该文件。路径不存在、是目录、
        或删除失败时返回以「delete_file 失败：」开头的说明。
        """
        resolved, err = _resolve_in_workspace(path)
        if err is not None or resolved is None:
            return f"delete_file 失败：{err}"

        if not resolved.exists():
            return f"delete_file 失败：文件不存在：{resolved}"
        if resolved.is_dir():
            return f"delete_file 失败：路径是目录（目录请用 run_cmd 等处理）：{resolved}"
        if not resolved.is_file():
            return f"delete_file 失败：不是常规文件：{resolved}"

        try:
            resolved.unlink()
        except OSError as err_unlink:
            return f"delete_file 失败：{err_unlink}"

        return f"delete_file OK: 已删除 {resolved}"

    @mcp.tool()
    def apply_file_patch(patch: str, path: str | None = None) -> str:
        """应用单文件 Codex 风格补丁（*** Begin Patch … *** End Patch）。

        一次调用**只处理一个** `*** Add File:` 或 `*** Update File:` 节。
        多文件请多次调用。不支持 `*** Delete File` / `*** Move to:`。

        参数：
        - patch：完整补丁文本（须含 Begin/End 信封）。Add：正文每行以 `+` 开头。
          Update：可按 `@@` 分多段，每段内先 `-` 行再 `+` 行；`-` 块须在目标文件中
          唯一匹配（首处替换）。在文件开头插入可让某段 `-` 为空而 `+` 非空。
        - path：可选；若提供则须与 patch 内文件路径解析到同一工作区文件，否则拒绝。

        与 edit_file 分工：熟悉 search/replace 用 edit_file；习惯 diff 式补丁用本工具。
        新建也可用 write_file；Add 与 Codex 对齐时使用本工具。

        仅工作区内路径；写入为原子替换；失败时返回以「apply_file_patch 失败：」开头。
        """
        parsed, resolved, before, err = _simulate_apply_file_patch(patch, path)
        if err is not None or parsed is None or resolved is None:
            return f"apply_file_patch 失败：{err}"

        if isinstance(parsed, _ParsedAdd):
            parent = resolved.parent
            if parent.exists() and not parent.is_dir():
                return f"apply_file_patch 失败：父路径不是目录：{parent}"
            if not parent.exists():
                try:
                    parent.mkdir(parents=True, exist_ok=True)
                except OSError as err_mk:
                    return f"apply_file_patch 失败：无法创建父目录：{err_mk}"
            try:
                _atomic_write_text(resolved, parsed.content)
            except OSError as err_write:
                return f"apply_file_patch 失败：写入失败：{err_write}"
            return f"apply_file_patch OK: 创建 {resolved}（{len(parsed.content)} 字节）"

        assert before is not None
        new_content, aerr = _apply_update_hunks(before, parsed.hunks)
        if aerr is not None or new_content is None:
            return f"apply_file_patch 失败：{aerr}"
        try:
            _atomic_write_text(resolved, new_content)
        except OSError as err_write:
            return f"apply_file_patch 失败：写入失败：{err_write}"
        return f"apply_file_patch OK: 已更新 {resolved}"

    # read_file: READ_FS（信任态自动放行）
    # 其余写入类：WRITE_FS（始终需要确认），附带预览
    return {
        "read_file": TrustCategory.READ_FS,
        "edit_file": ToolSpec(TrustCategory.WRITE_FS, preview=_preview_edit),
        "write_file": ToolSpec(TrustCategory.WRITE_FS, preview=_preview_write),
        "create_file": ToolSpec(TrustCategory.WRITE_FS, preview=_preview_create_file),
        "delete_file": ToolSpec(TrustCategory.WRITE_FS, preview=_preview_delete_file),
        "apply_file_patch": ToolSpec(TrustCategory.WRITE_FS, preview=_preview_apply_file_patch),
    }
