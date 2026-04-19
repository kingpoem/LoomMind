"""任务清单：进程内单例，由 plan / update_plan 工具驱动，在每轮 thought 注入上下文。"""

from enum import StrEnum


class TodoStatus(StrEnum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"


_STATUS_MARKER: dict[TodoStatus, str] = {
    TodoStatus.DONE: "✓",
    TodoStatus.DOING: "→",
    TodoStatus.TODO: "○",
}


class TodoItem:
    __slots__ = ("id", "content", "status")

    def __init__(self, item_id: str, content: str) -> None:
        self.id = item_id
        self.content = content
        self.status = TodoStatus.TODO


_todos: list[TodoItem] = []
_next_id: int = 1


def reset_plan(tasks: list[str]) -> list[TodoItem]:
    """用新列表替换当前清单，重置 ID 计数器。"""
    global _todos, _next_id
    _next_id = 1
    _todos = []
    for content in tasks:
        content = content.strip()
        if content:
            _todos.append(TodoItem(str(_next_id), content))
            _next_id += 1
    return list(_todos)


def update_items(
    done_ids: list[str] | None = None,
    doing_ids: list[str] | None = None,
    new_tasks: list[str] | None = None,
) -> list[TodoItem]:
    """批量更新状态并可追加新任务，返回更新后的完整清单。"""
    global _next_id
    id_map = {item.id: item for item in _todos}
    for eid in done_ids or []:
        if eid in id_map:
            id_map[eid].status = TodoStatus.DONE
    for eid in doing_ids or []:
        if eid in id_map:
            id_map[eid].status = TodoStatus.DOING
    for content in new_tasks or []:
        content = content.strip()
        if content:
            _todos.append(TodoItem(str(_next_id), content))
            _next_id += 1
    return list(_todos)


def get_context_block() -> str:
    """返回供注入上下文的任务清单文本；无清单时返回空串。

    全部完成后仍保留清单（添加提示），使模型不会重复已完成工作。
    """
    if not _todos:
        return ""
    lines = [
        f"{_STATUS_MARKER[item.status]} [{item.id}] {item.content}"
        for item in _todos
    ]
    all_done = all(item.status == TodoStatus.DONE for item in _todos)
    header = "## 任务清单（已全部完成）" if all_done else "## 任务清单"
    return header + "\n" + "\n".join(lines)


def current_todos() -> list[TodoItem]:
    return list(_todos)
