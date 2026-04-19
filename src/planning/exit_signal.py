"""工具退出信号：ask_user / finish_task 写入，observation 节点读取并清除。"""

_pending: tuple[str, str] | None = None  # (tool_name, message)


def set_exit(tool_name: str, message: str) -> None:
    global _pending
    _pending = (tool_name, message)


def take_exit() -> tuple[str, str] | None:
    """读取并清除当前退出信号；无信号时返回 None。"""
    global _pending
    result = _pending
    _pending = None
    return result
