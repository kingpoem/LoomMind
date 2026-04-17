"""多轮对话内容：序列化与持久化到仓库根目录下的 log/ 目录下"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import BaseMessage


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


class ContentManager:
    """管理当前会话消息并写入 log 目录下的 JSON 文件。"""

    def __init__(self, log_dir: Path | None = None) -> None:
        self.log_dir = log_dir or (_repo_root() / "log")
        self.session_id = (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + f"_{uuid4().hex[:8]}"
        )

    def session_payload(self, messages: list[BaseMessage]) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "updated_at": datetime.now(UTC).isoformat(),
            "messages": [m.model_dump(mode="json") for m in messages],
        }

    def dumps_session(self, messages: list[BaseMessage], *, indent: int = 2) -> str:
        return json.dumps(
            self.session_payload(messages), ensure_ascii=False, indent=indent
        )

    def persist(self, messages: list[BaseMessage]) -> Path:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"{self.session_id}.json"
        path.write_text(self.dumps_session(messages), encoding="utf-8")
        return path
