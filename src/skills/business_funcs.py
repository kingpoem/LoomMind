"""业务函数实现层（不绑定 LangChain Tool）。

这里的函数只负责“把输入变成输出”，不包含任何工具声明/元数据。
工具的 name/description/选择哪些函数暴露给 LLM，统一由 `skills_config.json`
和 `loader.py` 负责，从而实现“声明（JSON）”与“实现（Python）”解耦。

约束：
- 请务必写清楚函数签名的类型注解（LangChain 会据此推导参数 schema）。
- 返回值尽量使用 str / dict / list 等可 JSON 序列化的类型，便于模型理解与编排。
"""

import os


def check_banned_words(text: str) -> str:
    """检测文本是否包含违禁词；命中则返回固定提示，否则返回空字符串。

    可通过环境变量 `LOOMMIND_BANNED_WORDS`（逗号分隔）配置违禁词列表。
    未配置时使用内置示例词表。
    """

    raw = os.environ.get("LOOMMIND_BANNED_WORDS", "").strip()
    banned = [w.strip() for w in raw.split(",") if w.strip()] if raw else ["违禁词"]
    return "让我们换个话题" if any(w in text for w in banned) else ""

