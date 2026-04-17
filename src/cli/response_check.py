"""本地 CLI：检测用户输入控制指令。"""

from enum import Enum


class ResponseAction(Enum):
    """控制类指令与普通对话。"""

    NORMAL = "normal"
    EXIT = "exit"
    COMPASS = "compass"


def _normalize_control_text(text: str) -> str:
    return text.strip().lower()


def detect_reply_command(text: str) -> ResponseAction:
    """若整段文本在去空白并小写后恰好为控制指令，则返回对应动作。

    推荐使用 `/exit`、`/quit`、`/compass`；仍兼容无斜杠的 `exit` / `quit` / `compass`。
    """
    key = _normalize_control_text(text)
    if key in ("/exit", "exit", "/quit", "quit"):
        return ResponseAction.EXIT
    if key in ("/compass", "compass"):
        return ResponseAction.COMPASS
    return ResponseAction.NORMAL
