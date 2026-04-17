"""业务函数实现层（不绑定 LangChain Tool）。

这里的函数只负责“把输入变成输出”，不包含任何工具声明/元数据。
工具的 name/description/选择哪些函数暴露给 LLM，统一由 `skills_config.json`
和 `loader.py` 负责，从而实现“声明（JSON）”与“实现（Python）”解耦。

约束：
- 请务必写清楚函数签名的类型注解（LangChain 会据此推导参数 schema）。
- 返回值尽量使用 str / dict / list 等可 JSON 序列化的类型，便于模型理解与编排。
"""

