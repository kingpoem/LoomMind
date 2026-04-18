"""编排层状态（M2–M4）：与 `planning.loop.PlanningState` 分离。"""

from typing import Literal, NotRequired, TypedDict

from langchain_core.messages import BaseMessage


class OrchestrationMetadata(TypedDict, total=False):
    """预处理生成的 metadata（JSON 可序列化日志）。"""

    difficulty: Literal["trivial", "simple", "complex"]
    difficulty_score: int
    ask_or_plan: Literal["ask", "plan"]
    detected_url_or_file: bool
    history_token_estimate: int
    memory_retrieval_enabled: bool
    suggested_route: Literal["simple", "complex"]
    task_text: str
    tool_injection_suggestions: list[str]
    history_mode: str


class OrchestrationState(TypedDict):
    """外层编排图状态。

    `messages` 无 reducer：各节点返回**完整**列表（会话主线）。
    """

    messages: list[BaseMessage]
    orchestration_metadata: NotRequired[OrchestrationMetadata]
    orchestration_route: NotRequired[str]
    messages_checkpoint: NotRequired[list[BaseMessage]]
    reject_retry_count: NotRequired[int]
    max_review_reject_retries: NotRequired[int]
    review_verdict: NotRequired[str]
    exit_reason: NotRequired[str]
    after_review_route: NotRequired[Literal["end", "retry_simple", "retry_complex"]]
    complex_enabled_mcps: NotRequired[list[str]]
    complex_enabled_skills: NotRequired[list[str]]
    # --- M7 模块主管（complex 路径）---
    subtasks: NotRequired[list[dict[str, object]]]
    worker_summaries: NotRequired[list[str]]
    module_user_goal: NotRequired[str]
