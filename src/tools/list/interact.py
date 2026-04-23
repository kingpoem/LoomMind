"""ask_user / finish_task / notify 工具：规划循环的用户交互出口与中间叙述。"""

from mcp.server.fastmcp import FastMCP

from planning.exit_signal import set_exit
from tools.narrate import narrate as _narrate
from trust import TrustCategory


def register(mcp: FastMCP) -> dict[str, TrustCategory]:
    @mcp.tool()
    def ask_user(message: str) -> str:
        """向用户提问或说明，并立即结束本轮规划循环，等待用户回复。

        适用场景：需要用户补充信息、确认方向、或遇到歧义无法自行决策时调用。
        调用后规划图会立即终止，message 将作为本轮回复呈现给用户。

        参数 message：展示给用户的问题或说明（自然语言，不需要 JSON 包装）。
        """

        set_exit("ask_user", message)
        return "__ask_user__"

    @mcp.tool()
    def finish_task(message: str) -> str:
        """宣告任务已完成，向用户输出最终结论，并结束本轮规划循环。

        适用场景：所有子任务均已完成、有明确结论可以交付时调用。
        调用后规划图会立即终止，message 将作为本轮最终回复呈现给用户。

        参数 message：向用户呈现的最终结论或完成通知（自然语言）。
        """

        set_exit("finish_task", message)
        return "__finish_task__"

    @mcp.tool()
    def notify(message: str) -> str:
        """向用户发送一条中间进度消息，规划循环继续执行，不会终止。

        与 finish_task / ask_user 的本质区别：调用后循环不会停止，可继续调用其他工具。
        用于在执行长任务时让用户了解关键进展，而非沉默地执行一长串工具调用。

        使用约束（避免滥用）：
        - 只在有实质性结论可汇报时调用，例如"已分析完文件，发现 X 问题"。
        - 不要在工具调用前预告意图（"我将要读取…"）；
          应在获得结果后汇报发现（"已读取配置，确认端口为 8080"）。
        - 每完成一个执行阶段至多调用一次。

        参数 message：**简要的**进展说明，一到两句话，自然语言。
        """
        _narrate(message)
        return "ok"

    return {}
