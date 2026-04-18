"""用户每轮输入的解析结果（符号表）：布尔标志 + 交互模式枚举，供后续路由与优化。"""

import re
from dataclasses import dataclass
from enum import IntEnum


class ParsedInputMode(IntEnum):
    """当前仅定义 PLAN；后续可扩展其它交互模式。"""

    PLAN = 0


# http(s) / www / Markdown 链接中的 URL
_NETWORK_LINK_PATTERN = re.compile(
    r"(?:https?://[^\s<>\[\]()\"'`]+)"
    r"|(?:www\.[^\s<>\[\]()\"'`]+)"
    r"|(?:\[[^\]]*]\((https?://[^)\s]+)\))",
    re.IGNORECASE,
)


def user_input_contains_network_link(text: str) -> bool:
    """用户输入是否包含可识别的网络链接（http(s)、www、Markdown 链接）。"""
    if not (text or "").strip():
        return False
    return bool(_NETWORK_LINK_PATTERN.search(text))


def user_input_is_plan_mode(text: str) -> bool:
    """用户输入是否处于 plan 模式。

    当前产品仅支持该模式，默认为 True。后续可据前缀、指令或设置解析为 False。
    """
    _ = (text or "").strip()
    return True


@dataclass(frozen=True, slots=True)
class UserInputSymbolTable:
    """单轮用户输入解析后的符号表（可序列化字段）。"""

    has_network_link: bool
    is_plan_mode: bool
    interaction_mode: ParsedInputMode


def build_user_input_symbol_table(text: str) -> UserInputSymbolTable:
    """聚合各单项判断，生成本轮输入的符号表。"""
    has_network_link = user_input_contains_network_link(text)
    is_plan_mode = user_input_is_plan_mode(text)
    # 当前仅 PLAN；扩展其它 ParsedInputMode 时请与 is_plan_mode 等信号对齐分支
    interaction_mode = ParsedInputMode.PLAN
    return UserInputSymbolTable(
        has_network_link=has_network_link,
        is_plan_mode=is_plan_mode,
        interaction_mode=interaction_mode,
    )
