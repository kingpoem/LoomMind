"""plan / update_plan 工具：管理当前任务清单，供模型在规划时显式调用。"""

from mcp.server.fastmcp import FastMCP

from planning.todo import TodoStatus, reset_plan, update_items
from trust import TrustCategory

_STATUS_LABEL: dict[TodoStatus, str] = {
    TodoStatus.DONE: "✓",
    TodoStatus.DOING: "→",
    TodoStatus.TODO: "○",
}


def _render(todos) -> str:
    return "\n".join(f"{_STATUS_LABEL[item.status]} [{item.id}] {item.content}" for item in todos)


def register(mcp: FastMCP) -> dict[str, TrustCategory]:
    @mcp.tool()
    def plan(tasks: list[str]) -> str:
        """创建或重置当前任务清单。

        将任务按执行顺序传入，每项为一句话描述。调用后旧清单会被完全替换，
        新清单将在后续每轮对话的上下文中持续可见。

        适合在收到用户请求、确定步骤后立即调用，使规划可验证。
        完成某项后请调用 update_plan 更新状态。

        参数 tasks：有序任务列表，不可为空。
        """
        cleaned = [t.strip() for t in tasks if t.strip()]
        if not cleaned:
            return "plan 失败：tasks 不能为空"
        items = reset_plan(cleaned)
        return "已创建任务清单：\n" + _render(items)

    @mcp.tool()
    def update_plan(
        done_ids: list[str] | None = None,
        doing_ids: list[str] | None = None,
        add_tasks: list[str] | None = None,
    ) -> str:
        """更新任务清单状态，或追加新任务。

        参数（均可选，但至少提供一个）：
        - done_ids：标记为已完成的任务 ID 列表
        - doing_ids：标记为进行中的任务 ID 列表
        - add_tasks：追加到清单末尾的新任务描述列表

        示例：update_plan(done_ids=["1"], doing_ids=["2"], add_tasks=["补充验证"])
        """
        if not any([done_ids, doing_ids, add_tasks]):
            return "update_plan 失败：至少提供一个参数（done_ids / doing_ids / add_tasks）"
        items = update_items(done_ids=done_ids, doing_ids=doing_ids, new_tasks=add_tasks)
        if not items:
            return "update_plan 失败：当前无任务清单，请先调用 plan"
        return "更新后的任务清单：\n" + _render(items)

    # plan/update_plan 仅操作进程内状态，无需用户确认
    return {}
