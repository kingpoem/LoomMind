"""编排层开关（M2）。不读取时默认启用新编排。"""

import os

_LEGACY_VALUES = frozenset({"1", "true", "yes", "legacy", "old", "single"})


def use_legacy_planning_graph() -> bool:
    """为真时使用旧版单图 `build_graph()`，不经编排层 triage。

    环境变量：`LOOMMIND_ORCHESTRATION`
    - 未设置、空、或 `0` / `false` / `new`：使用新编排（默认）。
    - `1` / `true` / `yes` / `legacy` / `old`：使用旧版单图。
    """
    raw = os.environ.get("LOOMMIND_ORCHESTRATION", "").strip().lower()
    if not raw or raw in ("0", "false", "no", "new", "default"):
        return False
    return raw in _LEGACY_VALUES
