"""把内置 MCP server 的工具适配为 LangChain StructuredTool 列表。"""

import asyncio
import logging
import sys
from typing import Callable

from langchain_core.tools import StructuredTool
from mcp.types import TextContent

from .server import builtin_server, requires_confirmation

logger = logging.getLogger(__name__)

ConfirmationCallback = Callable[[str, dict], bool]


def _default_confirm(tool_name: str, args: dict) -> bool:
    """默认确认函数：在终端弹 y/N 提示；非 tty 环境一律拒绝。"""
    if not sys.stdin.isatty():
        logger.warning("工具 %s 需要确认，但 stdin 不是 tty，默认拒绝", tool_name)
        return False
    print(f"\n[confirmation] LLM 想调用工具: {tool_name}")
    for k, v in args.items():
        print(f"  {k} = {v!r}")
    ans = input("允许执行？[y/N] ").strip().lower()
    return ans in ("y", "yes")


_confirm_callback: ConfirmationCallback = _default_confirm


def set_confirmation_callback(cb: ConfirmationCallback) -> None:
    """覆盖默认确认函数。CLI 用默认 input()，Lark 等前端可按需替换。"""
    global _confirm_callback
    _confirm_callback = cb


def _stringify_content(content_list) -> str:
    """把 MCP 返回的 content 列表拼成纯文本。"""
    parts: list[str] = []
    for item in content_list:
        if isinstance(item, TextContent):
            parts.append(item.text)
        else:
            parts.append(str(item))
    return "\n".join(parts).strip() or "(no output)"


def _make_tool(name: str, description: str, input_schema: dict) -> StructuredTool:
    needs_confirm = requires_confirmation(name)

    async def arun(**kwargs) -> str:
        if needs_confirm and not _confirm_callback(name, kwargs):
            return f"Tool call '{name}' denied by user."
        content, _structured = await builtin_server.call_tool(name, kwargs)
        return _stringify_content(content)

    def run(**kwargs) -> str:
        return asyncio.run(arun(**kwargs))

    return StructuredTool.from_function(
        func=run,
        coroutine=arun,
        name=name,
        description=description or "",
        args_schema=input_schema,
    )


def load_tools() -> list[StructuredTool]:
    """从 BuiltinServer 拉取已注册工具，返回 LangChain StructuredTool 列表。"""
    try:
        mcp_tools = asyncio.run(builtin_server.list_tools())
    except Exception:
        logger.exception("从 BuiltinServer 拉取工具列表失败")
        return []

    tools: list[StructuredTool] = []
    for t in mcp_tools:
        try:
            tools.append(_make_tool(t.name, t.description or "", t.inputSchema))
        except Exception:
            logger.exception("适配 MCP 工具到 LangChain 失败: %s", t.name)
    return tools
