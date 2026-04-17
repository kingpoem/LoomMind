"""raw JSON 转 content 下 system:/user:/ai: 文本；供 export_log_txt 与批处理调用。"""

import json
from pathlib import Path
from typing import Any


def _default_log_root() -> Path:
    return Path(__file__).resolve().parents[1] / "log"


def lines_from_stored_messages(messages: list[dict[str, Any]]) -> list[str]:
    """从持久化消息列表中提取 system / user / ai 行。"""
    lines: list[str] = []
    for m in messages:
        mtype = m.get("type")
        content = m.get("content", "")
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(str(block))
            content = "".join(parts)
        elif not isinstance(content, str):
            content = str(content)
        if mtype == "system":
            lines.append(f"system: {content}")
        elif mtype == "human":
            lines.append(f"user: {content}")
        elif mtype == "ai":
            lines.append(f"ai: {content}")
    return lines


def sync_raw_json_to_content_txt(
    raw_json_path: Path, *, log_root: Path | None = None
) -> Path:
    """读取单个 raw JSON，写入同会话名的 log/content/*.txt。"""
    path = raw_json_path.resolve()
    root = log_root if log_root is not None else path.parent.parent
    out_dir = root / "content"
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    msgs = data.get("messages", [])
    if not isinstance(msgs, list):
        msgs = []
    lines = lines_from_stored_messages(msgs)
    text = "\n".join(lines)
    if text:
        text += "\n"
    out_path = out_dir / f"{path.stem}.txt"
    out_path.write_text(text, encoding="utf-8")
    return out_path


def export_raw_logs_to_txt(*, log_root: Path | None = None) -> list[Path]:
    """批量处理 log/raw/*.json → log/content/*.txt。"""
    root = log_root or _default_log_root()
    raw_dir = root / "raw"
    out_dir = root / "content"
    if not raw_dir.is_dir():
        out_dir.mkdir(parents=True, exist_ok=True)
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path in sorted(raw_dir.glob("*.json")):
        written.append(sync_raw_json_to_content_txt(path, log_root=root))
    return written
