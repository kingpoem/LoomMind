"""会话 JSON 写入 log/raw/。导出 txt 见 scripts/export_log_txt.py 与 make log。"""

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
        self.raw_dir = log_dir or (_repo_root() / "log" / "raw")
        self.session_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + f"_{uuid4().hex[:8]}"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def session_payload(self, messages: list[BaseMessage]) -> dict[str, Any]:
        """返回含 session_id、updated_at 与 messages 的可 JSON 化字典。"""
        return {
            "session_id": self.session_id,
            "updated_at": datetime.now(UTC).isoformat(),
            "messages": [m.model_dump(mode="json") for m in messages],
        }

    def dumps_session(self, messages: list[BaseMessage], *, indent: int = 2) -> str:
        """将当前会话快照序列化为 JSON 字符串。"""
        return json.dumps(self.session_payload(messages), ensure_ascii=False, indent=indent)

    def persist(self, messages: list[BaseMessage]) -> Path:
        """把当前消息列表写入 log/raw/<session_id>.json 并返回路径。"""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        path = self.raw_dir / f"{self.session_id}.json"
        path.write_text(self.dumps_session(messages), encoding="utf-8")
        return path
