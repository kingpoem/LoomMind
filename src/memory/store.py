"""仓库根目录 `memory/` 下文件的读写与 compass 摘要落盘。"""

import shutil
from datetime import UTC, datetime
from pathlib import Path

_MEMORY_DIRNAME = "memory"
_TEMPLATE_DIRNAME = "template"
_SUMMARY_NAME = "memory_summary.md"
_HANDBOOK_NAME = "MEMORY.md"
_MEMORY_SEEDS: tuple[tuple[str, str], ...] = (
    ("MEMORY.md.tmpl", "MEMORY.md"),
    ("memory_summary.md.tmpl", "memory_summary.md"),
    ("planning_long_term.md.tmpl", "planning_long_term.md"),
)
_MAX_DIGEST_CHARS = 4000
_MAX_SUMMARY_FILE_CHARS = 48_000


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def memory_dir() -> Path:
    return repo_root() / _MEMORY_DIRNAME


def template_dir() -> Path:
    return repo_root() / _TEMPLATE_DIRNAME


def memory_summary_path() -> Path:
    return memory_dir() / _SUMMARY_NAME


def memory_handbook_path() -> Path:
    return memory_dir() / _HANDBOOK_NAME


def ensure_memory_files() -> None:
    """首次本地运行时从 `template/*.tmpl` 复制到 `memory/`（目标已存在则跳过）。"""
    d = memory_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmpl_root = template_dir()
    for tmpl_name, dest_name in _MEMORY_SEEDS:
        dest = d / dest_name
        if dest.is_file():
            continue
        src = tmpl_root / tmpl_name
        if src.is_file():
            shutil.copy2(src, dest)
            continue
        if dest_name == _SUMMARY_NAME:
            dest.write_text(
                "# 记忆概述\n\n由 compass 压缩会话时自动追加摘要；可手动编辑。\n\n",
                encoding="utf-8",
            )
        elif dest_name == _HANDBOOK_NAME:
            dest.write_text(
                "# 记忆手册\n\n长期约定与术语；会话启动时会节选注入系统提示。\n\n",
                encoding="utf-8",
            )
        elif dest_name == "planning_long_term.md":
            dest.write_text("# 长期规划记忆\n\n", encoding="utf-8")


def read_memory_summary() -> str:
    ensure_memory_files()
    return memory_summary_path().read_text(encoding="utf-8").strip()


def read_handbook(*, max_chars: int | None = None) -> str:
    ensure_memory_files()
    text = memory_handbook_path().read_text(encoding="utf-8").strip()
    if max_chars is not None and len(text) > max_chars:
        suffix = "\n\n…（已截断，完整内容见 memory/MEMORY.md）"
        return text[:max_chars].rstrip() + suffix
    return text


def _trim_summary_file(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    if len(raw) <= _MAX_SUMMARY_FILE_CHARS:
        return
    head = raw[:2000]
    tail_len = _MAX_SUMMARY_FILE_CHARS - len(head) - 40
    tail = raw[-tail_len:] if tail_len > 0 else ""
    path.write_text(head + "\n\n…（中间已省略过长历史）\n\n" + tail, encoding="utf-8")


def record_compass_digest(summary: str) -> None:
    """compass 成功压缩后，将摘要写入 memory_summary（带时间戳）。"""
    text = summary.strip()
    if not text:
        return
    if len(text) > _MAX_DIGEST_CHARS:
        text = text[:_MAX_DIGEST_CHARS].rstrip() + "…"
    ensure_memory_files()
    path = memory_summary_path()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    block = f"\n\n---\n*{stamp} · compass*\n\n{text}\n"
    path.write_text(path.read_text(encoding="utf-8").rstrip() + block, encoding="utf-8")
    _trim_summary_file(path)
