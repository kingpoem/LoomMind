from __future__ import annotations

"""从本地 JSON “声明库”动态加载 Skills（LangChain Tools）。

设计目标：
- 让非技术人员只改 `skills_config.json` 的 name/description 来影响对模型暴露的工具描述；
- 让技术人员只在 `business_funcs.py` 写业务逻辑；
- 运行时将 JSON 配置 + Python 函数合成为可 `llm.bind_tools()` 的 `StructuredTool` 列表。

`skills_config.json` schema（数组）：
[
  {
    "name": "tool_name_for_llm",
    "description": "human readable description for LLM",
    "handler": "python_function_key"
  }
]
"""

import inspect
import json
from pathlib import Path
from typing import Any, Callable

from langchain_core.tools import StructuredTool

from . import business_funcs


def _build_function_registry() -> dict[str, Callable[..., Any]]:
    """从 `business_funcs` 自动收集可暴露的业务函数。"""

    registry: dict[str, Callable[..., Any]] = {}
    for name, obj in inspect.getmembers(business_funcs, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        if getattr(obj, "__module__", None) != business_funcs.__name__:
            continue
        registry[name] = obj
    return registry


# handler -> callable 映射表（自动生成，后续新增 skill 不需要改 loader.py）
FUNCTION_REGISTRY: dict[str, Callable[..., Any]] = _build_function_registry()


def _skills_config_path() -> Path:
    """默认配置文件路径：与本模块同目录的 `skills_config.json`。"""

    return Path(__file__).with_name("skills_config.json")


def validate_skills_config(raw: Any) -> None:
    """校验 skills_config.json 的结构与可用性（失败直接抛异常）。"""

    if not isinstance(raw, list):
        raise TypeError("skills_config.json 必须是一个 JSON 数组")

    seen_names: set[str] = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise TypeError(f"skills_config.json[{idx}] 必须是一个 JSON 对象")

        name = item.get("name")
        description = item.get("description")
        handler_key = item.get("handler")

        if not isinstance(name, str) or not name:
            raise ValueError(f"skills_config.json[{idx}].name 必须是非空字符串")
        if name in seen_names:
            raise ValueError(f"skills_config.json 工具 name 重复：{name!r}")
        seen_names.add(name)

        if not isinstance(description, str) or not description:
            raise ValueError(f"skills_config.json[{idx}].description 必须是非空字符串")
        if not isinstance(handler_key, str) or not handler_key:
            raise ValueError(f"skills_config.json[{idx}].handler 必须是非空字符串")

        fn = FUNCTION_REGISTRY.get(handler_key)
        if fn is None:
            raise KeyError(
                f"skills_config.json[{idx}] handler={handler_key!r} 未找到。"
                f"请确认 `business_funcs.py` 中存在同名函数 {handler_key!r}（且不以下划线开头）。"
            )
        if not callable(fn):
            raise TypeError(
                f"skills_config.json[{idx}] handler={handler_key!r} 指向对象不可调用：{type(fn)!r}"
            )


def load_all_skills(config_path: str | Path | None = None) -> list[StructuredTool]:
    """加载并构建所有 skills（StructuredTool）。"""

    path = Path(config_path) if config_path is not None else _skills_config_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    validate_skills_config(raw)

    tools: list[StructuredTool] = []
    for item in raw:
        name = item.get("name")
        description = item.get("description")
        handler_key = item.get("handler")

        fn = FUNCTION_REGISTRY.get(handler_key)

        tool = StructuredTool.from_function(
            func=fn,
            name=str(name),
            description=str(description),
        )
        tools.append(tool)

    return tools

