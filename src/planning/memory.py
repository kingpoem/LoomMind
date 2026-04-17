"""规划模块的长期记忆读写。"""

from datetime import UTC, datetime
from pathlib import Path

from memory.store import memory_dir

_PLANNING_MEMORY_FILE = "planning_long_term.md"
_MAX_FILE_CHARS = 24_000
_MAX_ENTRY_CHARS = 800


def planning_memory_path() -> Path:
    d = memory_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / _PLANNING_MEMORY_FILE
    if not path.exists():
        path.write_text("# Planning 长期记忆\n\n", encoding="utf-8")
    return path


def read_long_term_memories(*, limit: int = 6) -> list[str]:
    raw = planning_memory_path().read_text(encoding="utf-8").strip()
    if not raw:
        return []
    lines = [
        line.strip("- ").strip() for line in raw.splitlines() if line.startswith("- ")
    ]
    if limit <= 0:
        return []
    return lines[-limit:]


def _trim_file(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    if len(raw) <= _MAX_FILE_CHARS:
        return
    head = raw[:1200]
    tail = raw[-(_MAX_FILE_CHARS - len(head) - 32) :]
    path.write_text(head + "\n\n…（中间已裁剪）\n\n" + tail, encoding="utf-8")


def append_long_term_memory(entry: str) -> None:
    text = entry.strip()
    if not text:
        return
    if len(text) > _MAX_ENTRY_CHARS:
        text = text[:_MAX_ENTRY_CHARS].rstrip() + "…"
    path = planning_memory_path()
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    line = f"- [{ts}] {text}\n"
    path.write_text(path.read_text(encoding="utf-8") + line, encoding="utf-8")
    _trim_file(path)
