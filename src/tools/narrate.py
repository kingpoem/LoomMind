"""向用户推送中间进度消息的回调机制。

与工具调用通知（tool_invoked）不同，这里传递的是模型主动叙述的内容。
前端可通过 set_narrate_callback 替换默认行为。
"""

from collections.abc import Callable

NarrateFn = Callable[[str], None]

_callback: NarrateFn | None = None


def set_narrate_callback(fn: NarrateFn) -> None:
    """设置叙述回调；stdio 前端传入 emit assistant_delta，tty 保持默认 print。"""
    global _callback
    _callback = fn


def narrate(message: str) -> None:
    """推送一条中间进度消息。未设置回调时回退到 stdout print。"""
    if _callback is not None:
        _callback(message)
    else:
        print(f"\n{message}", flush=True)
