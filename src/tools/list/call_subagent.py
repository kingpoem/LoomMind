"""call_subagent 工具：将独立子任务委托给嵌套规划 Agent，返回最终答复文本。"""

import threading

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from mcp.server.fastmcp import FastMCP

from planning.loop import build_planning_graph
from tools.subagent_context import (
    get_permission_callback,
    set_allowed_categories,
)
from trust import TrustCategory

# 子 Agent 不开放的工具——防递归、防全局状态污染
_EXCLUDED_TOOLS = frozenset({"call_subagent", "ask_user", "finish_task", "notify", "plan", "update_plan"})

_DEFAULT_MAX_CYCLES = 6
_MAX_CYCLES_CAP = 12
_DEPTH_MAX = 3

# 每个线程独立的嵌套深度计数，避免 Feishu 多线程互相干扰
_thread_local = threading.local()

_SUB_AGENT_SYSTEM = "你是一个子 Agent，负责完成上级 Agent 委托的特定子任务。请独立完成任务并直接输出结论，无需调用 finish_task 或 ask_user。"


def _depth() -> int:
    return getattr(_thread_local, "depth", 0)


def register(mcp: FastMCP) -> dict[str, TrustCategory]:
    @mcp.tool()
    def call_subagent(prompt: str, max_cycles: int = _DEFAULT_MAX_CYCLES) -> str:
        """将独立子任务委托给嵌套的规划 Agent，待其完成后返回最终答复文本。

        子 Agent 拥有与主 Agent 相同的工作区工具访问权限，但不能递归调用
        call_subagent（防止无限嵌套；最大深度 3）。plan / update_plan /
        ask_user / finish_task 也不对子 Agent 开放，以防止干扰上级任务状态。

        适合场景：
        - 将复杂任务拆分为互相独立的步骤分别委托执行
        - 对文件、代码作深度分析而不污染主循环的短期记忆
        - 生成草稿或中间产物，再由主 Agent 审查整合

        参数 prompt：子任务的完整描述及期望的输出格式，应包含足够的上下文。
        参数 max_cycles：子 Agent 最大循环次数（1–12，默认 6）。
        """
        current = _depth()
        if current >= _DEPTH_MAX:
            return f"call_subagent 失败：嵌套深度已达上限（{_DEPTH_MAX}），拒绝调用"

        cycles = max(1, min(int(max_cycles), _MAX_CYCLES_CAP))

        from tools.loader import load_tools  # noqa: PLC0415 — 延迟导入，避免循环依赖

        all_tools = load_tools()
        sub_tools = [t for t in all_tools if getattr(t, "name", "") not in _EXCLUDED_TOOLS]

        graph = build_planning_graph(tools=sub_tools, max_cycles=cycles)

        # 获取子 Agent 的工具类别权限
        cb = get_permission_callback()
        if cb is not None:
            # stdio/TUI 模式：向用户弹出权限选择框
            allowed: frozenset[TrustCategory] | None = cb()
            if allowed is None:
                return "子 Agent 启动已取消（用户未授权权限）"
        else:
            # tty 模式：不预授权，各工具仍会单独弹出确认
            allowed = None

        _thread_local.depth = current + 1
        set_allowed_categories(allowed)
        try:
            result = graph.invoke(
                {
                    "messages": [
                        SystemMessage(content=_SUB_AGENT_SYSTEM),
                        HumanMessage(content=prompt),
                    ]
                }
            )
        finally:
            set_allowed_categories(None)
            _thread_local.depth = current

        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, str) and content.strip():
                    return content
                if not isinstance(content, str):
                    return str(content)
        return "子 Agent 未返回有效结果"

    return {"call_subagent": TrustCategory.EXEC}
