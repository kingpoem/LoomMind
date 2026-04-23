"""ask_user / finish_task 工具：终止当前规划循环并向用户输出消息。"""

from mcp.server.fastmcp import FastMCP

from planning.exit_signal import set_exit
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

    return {}
