"""内置 MCP server：扫描 src/tools/list/ 下的模块并注册其工具。"""

import importlib
import logging
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from trust import TrustCategory

logger = logging.getLogger(__name__)

builtin_server = FastMCP("BuiltinServer", json_response=True)

_tools_requiring_confirmation: set[str] = set()
_tool_categories: dict[str, TrustCategory] = {}


def requires_confirmation(tool_name: str) -> bool:
    """该工具在被 LLM 调用前是否需要用户显式确认。"""
    return tool_name in _tools_requiring_confirmation


def tool_category(tool_name: str) -> TrustCategory | None:
    """返回该工具登记的信任类别；未登记返回 None。"""
    return _tool_categories.get(tool_name)


def _ingest_register_result(module_name: str, result) -> None:
    """把 `register(mcp)` 的返回值登记到确认集合与类别表。

    兼容三种形状：
    - `Iterable[str]`：旧行为，登记为「需确认，类别视作最严格的 EXEC」。
    - `Iterable[tuple[str, TrustCategory]]`：显式声明类别。
    - `Mapping[str, TrustCategory]`：显式声明类别（推荐）。
    """
    if result is None:
        return
    pairs: list[tuple[str, TrustCategory]] = []
    if isinstance(result, Mapping):
        for name, cat in result.items():
            if not isinstance(name, str) or not isinstance(cat, TrustCategory):
                logger.warning(
                    "%s.register 返回 Mapping 项类型错误：%r -> %r，忽略",
                    module_name,
                    name,
                    cat,
                )
                continue
            pairs.append((name, cat))
    elif isinstance(result, Iterable):
        for item in result:
            if isinstance(item, str):
                # 旧风格：默认作为 EXEC 处理，信任态也不会自动放行。
                pairs.append((item, TrustCategory.EXEC))
                continue
            if (
                isinstance(item, tuple)
                and len(item) == 2
                and isinstance(item[0], str)
                and isinstance(item[1], TrustCategory)
            ):
                pairs.append((item[0], item[1]))
                continue
            logger.warning("%s.register 返回项无法识别：%r，忽略", module_name, item)
    else:
        logger.warning("%s.register 返回值不可迭代：%r，忽略", module_name, result)
        return

    for name, cat in pairs:
        _tools_requiring_confirmation.add(name)
        _tool_categories[name] = cat


def _load_builtin_tools() -> None:
    """导入 src/tools/list/*.py，调用其 register(mcp) 注册工具。

    register(mcp) 的返回值描述「调用前需用户确认」的工具及其信任类别，
    具体形状见 `_ingest_register_result`。
    """
    list_dir = Path(__file__).parent / "list"
    if not list_dir.is_dir():
        return

    for path in sorted(list_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"tools.list.{path.stem}"
        try:
            module = importlib.import_module(mod_name)
        except Exception:
            logger.exception("加载工具模块失败: %s", mod_name)
            continue
        register: Callable[[FastMCP], object] | None = getattr(module, "register", None)
        if not callable(register):
            continue
        try:
            result = register(builtin_server)
        except Exception:
            logger.exception("注册工具失败: %s", mod_name)
            continue
        _ingest_register_result(mod_name, result)


_load_builtin_tools()
