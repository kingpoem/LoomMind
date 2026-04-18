"""子任务结构化描述（M7）：不携带父级完整 messages。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

SubTaskRole = Literal["code", "reasoning", "generic"]


class SubTaskItem(BaseModel):
    """单个子任务（映射为子图输入，仅用 description/context）。"""

    id: str = Field(description="子任务编号，如 1、2")
    title: str = Field(default="", description="短标题")
    description: str = Field(description="子任务说明，执行器仅依赖此字段即可开工")
    context_data: str = Field(
        default="",
        description="可选补充材料（非父会话全文，仅摘录）",
    )
    role: SubTaskRole = Field(
        default="generic",
        description="子执行器画像：code=偏文件/命令；reasoning=偏只读与推理；generic=与会话默认一致",
    )

    @field_validator("role", mode="before")
    @classmethod
    def _coerce_role(cls, v: object) -> str:
        if v in (None, ""):
            return "generic"
        r = str(v).strip().lower()
        if r in ("code", "reasoning", "generic"):
            return r
        return "generic"


class DecomposeOutput(BaseModel):
    """分解输出：至少 1 条，由后处理保证 Plan 场景 >=2。"""

    subtasks: list[SubTaskItem] = Field(
        ...,
        description="有序子任务列表",
        min_length=1,
        max_length=8,
    )


def ensure_min_subtasks(items: list[SubTaskItem], *, min_n: int = 2) -> list[SubTaskItem]:
    """若模型只给出 1 条，则追加复核子任务，满足 Plan 验收下限。"""
    out = list(items)
    if len(out) >= min_n:
        return out
    n = len(out) + 1
    out.append(
        SubTaskItem(
            id=str(n),
            title="复核与补全",
            description=(
                "基于上一子任务输出与用户总目标，检查是否遗漏关键步骤或结论；"
                "只做补充说明，不重复已完成工作。"
            ),
            role="reasoning",
        )
    )
    return out
