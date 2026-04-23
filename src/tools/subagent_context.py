"""子 Agent 权限上下文：跨模块共享的线程局部存储与权限回调。"""

import threading
from collections.abc import Callable

from trust import TrustCategory

_tl = threading.local()

SubagentPermissionFn = Callable[[], "frozenset[TrustCategory] | None"]
_permission_callback: SubagentPermissionFn | None = None


def set_subagent_permission_callback(fn: SubagentPermissionFn) -> None:
    """注册子 Agent 权限请求回调（stdio 前端在 run_cli_stdio 中调用）。"""
    global _permission_callback
    _permission_callback = fn


def get_permission_callback() -> SubagentPermissionFn | None:
    return _permission_callback


def set_allowed_categories(cats: "frozenset[TrustCategory] | None") -> None:
    """在当前线程设置子 Agent 允许的工具类别；None 表示不在子 Agent 上下文中。"""
    _tl.allowed_categories = cats


def get_allowed_categories() -> "frozenset[TrustCategory] | None":
    """返回当前线程的子 Agent 权限集合，不在子 Agent 上下文时返回 None。"""
    return getattr(_tl, "allowed_categories", None)
