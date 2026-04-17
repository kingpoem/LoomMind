"""仓库根目录 memory/ 的读写，以及与系统提示的互注。"""

from .injection import build_system_prompt_with_memory
from .store import (
    ensure_memory_files,
    memory_dir,
    read_handbook,
    read_memory_summary,
    record_compass_digest,
    repo_root,
)

__all__ = [
    "build_system_prompt_with_memory",
    "ensure_memory_files",
    "memory_dir",
    "read_handbook",
    "read_memory_summary",
    "record_compass_digest",
    "repo_root",
]
