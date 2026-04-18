"""内置 MCP server：扫描 src/tools/list/ 下的模块并注册其工具。"""

import importlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from trust import TrustCategory

logger = logging.getLogger(__name__)

builtin_server = FastMCP("BuiltinServer", json_response=True)


PreviewFn = Callable[[dict], str | None]


@dataclass(frozen=True)
class ToolSpec:
    """工具的登记元数据。

    - `category`: 信任类别，决定 `trust.auto_approve` 是否能跳过确认。
    - `preview`: 可选函数，接收工具参数 dict 并返回一段人类可读的预览
      （通常是 diff）。在确认请求中附带展示，便于用户判断"这次到底要改什么"。
    """

    category: TrustCategory
    preview: PreviewFn | None = None


_tools_requiring_confirmation: set[str] = set()
_tool_categories: dict[str, TrustCategory] = {}
_tool_previews: dict[str, PreviewFn] = {}


def requires_confirmation(tool_name: str) -> bool:
    """该工具在被 LLM 调用前是否需要用户显式确认。"""
    return tool_name in _tools_requiring_confirmation


def tool_category(tool_name: str) -> TrustCategory | None:
    """返回该工具登记的信任类别；未登记返回 None。"""
    return _tool_categories.get(tool_name)


def tool_preview(tool_name: str) -> PreviewFn | None:
    """返回该工具的预览函数；未登记返回 None。"""
    return _tool_previews.get(tool_name)


def _coerce_spec(value) -> ToolSpec | None:
    """把登记值归一化为 `ToolSpec`；无法识别返回 None。"""
    if isinstance(value, ToolSpec):
        return value
    if isinstance(value, TrustCategory):
        return ToolSpec(value)
    return None


def _ingest_register_result(module_name: str, result) -> None:
    """把 `register(mcp)` 的返回值登记到确认集合、类别表、预览表。

    须为 `Mapping[str, TrustCategory | ToolSpec]`。
    """
    if result is None:
        return
    if not isinstance(result, Mapping):
        logger.warning(
            "%s.register 须返回 Mapping[str, TrustCategory | ToolSpec]，收到 %r，忽略",
            module_name,
            type(result).__name__,
        )
        return
    pairs: list[tuple[str, ToolSpec]] = []
    for name, value in result.items():
        spec = _coerce_spec(value)
        if not isinstance(name, str) or spec is None:
            logger.warning(
                "%s.register 返回 Mapping 项类型错误：%r -> %r，忽略",
                module_name,
                name,
                value,
            )
            continue
        pairs.append((name, spec))

    for name, spec in pairs:
        _tools_requiring_confirmation.add(name)
        _tool_categories[name] = spec.category
        if spec.preview is not None:
            _tool_previews[name] = spec.preview


def _load_builtin_tools() -> None:
    """导入 src/tools/list/*.py，调用其 register(mcp) 注册工具。

    register(mcp) 的返回值须为 Mapping，描述「调用前需用户确认」的工具及其信任类别。
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
