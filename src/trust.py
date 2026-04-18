"""进程内工作区信任态：启动时由用户一次性抉择，贯穿整个会话。

- `is_trusted()` 被 `tools/loader.py` 查询以决定是否跳过确认；
- `workspace_root()` 被 `memory/injection.py` 注入到系统提示；
- 工具分类 `TrustCategory` 由 `tools/server.py` 登记，`auto_approve` 只放行
  「信任后也应当直接放行」的类别（当前仅 READ_FS）。
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from pathlib import Path


class TrustCategory(enum.Enum):
    READ_FS = "read_fs"
    WRITE_FS = "write_fs"
    EXEC = "exec"
    NETWORK = "network"


_AUTO_APPROVE_WHEN_TRUSTED: frozenset[TrustCategory] = frozenset(
    {TrustCategory.READ_FS}
)

_trusted: bool = False
_workspace_root: Path | None = None


def workspace_root() -> Path:
    """当前工作区绝对路径，首次调用时定住 `Path.cwd()`。"""
    global _workspace_root
    if _workspace_root is None:
        _workspace_root = Path.cwd().resolve()
    return _workspace_root


def is_trusted() -> bool:
    return _trusted


def set_trusted(value: bool) -> None:
    global _trusted
    _trusted = bool(value)


def auto_approve(tool_name: str) -> bool:
    """信任态下该工具是否免确认。

    仅当已信任、且工具类别在 `_AUTO_APPROVE_WHEN_TRUSTED` 集合里，才返回 True。
    未登记类别的工具（例如老代码只声明了「需要确认」）一律视作敏感，不自动放行。
    """
    if not _trusted:
        return False
    # 延迟导入，避免循环依赖：trust 是底层模块，tools/server 依赖它。
    from tools.server import tool_category

    cat = tool_category(tool_name)
    if cat is None:
        return False
    return cat in _AUTO_APPROVE_WHEN_TRUSTED


def prompt_for_trust(prompter: Callable[[Path], bool]) -> bool:
    """由各前端提供 prompter；其返回值被记入全局态。"""
    decision = bool(prompter(workspace_root()))
    set_trusted(decision)
    return decision
