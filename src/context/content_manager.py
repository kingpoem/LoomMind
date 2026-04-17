"""会话 JSON 写入 log/raw/。导出纯文本见 scripts/export_log_txt.py。"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import BaseMessage


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


class ContentManager:
    """管理当前会话消息并写入 log/raw/ 下的 JSON 文件。"""

    def __init__(self, log_dir: Path | None = None) -> None:
        # log_dir 表示存放 *.json 的目录（默认 log/raw）
        self.raw_dir = log_dir or (_repo_root() / "log" / "raw")
        self.log_root = self.raw_dir.parent
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
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        path = self.raw_dir / f"{self.session_id}.json"
        path.write_text(self.dumps_session(messages), encoding="utf-8")
        return path
