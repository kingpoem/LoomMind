"""进程内工作区信任态：启动时由用户一次性抉择，贯穿整个会话。

- `is_trusted()` 被 `tools/loader.py` 查询以决定是否跳过确认；
- `workspace_root()` 被 `memory/injection.py` 注入到系统提示；
- 工具分类 `TrustCategory` 由 `tools/server.py` 登记，`auto_approve` 只放行
  「信任后也应当直接放行」的类别（当前仅 READ_FS）。
- 持久化：`settings.json` 的 `trust.trusted_paths`（绝对路径字符串列表）。
  当前工作区路径若与列表中任一条相同，或是其中某条的子路径，则视为已信任。
"""

import enum
from collections.abc import Callable
from pathlib import Path

from settings import get, merge_trust_add_trusted_path


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


def _trusted_paths_from_settings() -> list[str]:
    raw = get("trust.trusted_paths", [])
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def workspace_matches_trusted_paths(workspace: Path, trusted_paths: list[str]) -> bool:
    """若 `workspace` 解析后与列表中某条相同，或是该条的子路径，则返回 True。"""
    try:
        p = workspace.resolve()
    except OSError:
        return False
    for entry in trusted_paths:
        try:
            root = Path(entry).resolve()
        except OSError:
            continue
        if p == root or p.is_relative_to(root):
            return True
    return False


def is_persisted_workspace_trusted() -> bool:
    """当前 `workspace_root()` 是否落在 `trust.trusted_paths` 的信任范围内。"""
    return workspace_matches_trusted_paths(
        workspace_root(), _trusted_paths_from_settings()
    )


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


def ensure_trust_at_startup(prompter: Callable[[Path], bool]) -> bool:
    """启动时解析工作区信任：已写入 settings 则直接跳过弹窗，否则调用 prompter。

    已信任：仅 `set_trusted(True)`，不发送 `trust_request`（stdio/TUI 无遮挡）。
    未信任：执行 `prompter`（如弹出是否信任）；用户同意则把当前工作区绝对路径写入列表。
    返回最终是否处于信任态。
    """
    if is_persisted_workspace_trusted():
        set_trusted(True)
        return True
    root = workspace_root()
    decision = bool(prompter(root))
    set_trusted(decision)
    if decision:
        merge_trust_add_trusted_path(root)
    return decision
