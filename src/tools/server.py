"""内置 MCP server：扫描 src/tools/list/ 下的模块并注册其工具。"""

import importlib
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

builtin_server = FastMCP("BuiltinServer", json_response=True)

_tools_requiring_confirmation: set[str] = set()


def requires_confirmation(tool_name: str) -> bool:
    """该工具在被 LLM 调用前是否需要用户显式确认。"""
    return tool_name in _tools_requiring_confirmation


def _load_builtin_tools() -> None:
    """导入 src/tools/list/*.py，调用其 register(mcp) 注册工具。

    register(mcp) 的返回值若为可迭代对象，其中的工具名会被登记为
    「调用前需用户确认」，由 loader.py 的客户端拦截执行。
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
        register = getattr(module, "register", None)
        if not callable(register):
            continue
        try:
            result = register(builtin_server)
        except Exception:
            logger.exception("注册工具失败: %s", mod_name)
            continue
        if result is None:
            continue
        try:
            _tools_requiring_confirmation.update(result)
        except TypeError:
            logger.warning("%s.register 返回值不可迭代，已忽略", mod_name)


_load_builtin_tools()
