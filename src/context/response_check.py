"""检测用户输入或模型回答中的控制指令"""

from enum import Enum


class ResponseAction(Enum):
    """控制类指令与普通对话。"""

    NORMAL = "normal"
    EXIT = "exit"
    LOG = "log"


def _normalize_control_text(text: str) -> str:
    return text.strip().lower()


def detect_reply_command(text: str) -> ResponseAction:
    """若整段文本在去空白并小写后恰好为 exit 或 log，则返回对应动作。"""
    key = _normalize_control_text(text)
    if key == "exit":
        return ResponseAction.EXIT
    if key == "log":
        return ResponseAction.LOG
    return ResponseAction.NORMAL
