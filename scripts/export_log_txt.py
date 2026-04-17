"""将 log/raw/*.json 中的 human/ai 轮次导出为 log/content/*.txt（user:/ai:）。"""

import json
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def lines_from_stored_messages(messages: list[dict[str, Any]]) -> list[str]:
    """从持久化消息列表中提取 user/ai 行（不含 system）。"""
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
        if mtype == "human":
            lines.append(f"user: {content}")
        elif mtype == "ai":
            lines.append(f"ai: {content}")
    return lines


def export_raw_logs_to_txt(*, log_root: Path | None = None) -> list[Path]:
    """读取 log/raw/*.json，将 human/ai 轮次写入 log/content/*.txt。"""
    root = log_root or (_repo_root() / "log")
    raw_dir = root / "raw"
    out_dir = root / "content"
    if not raw_dir.is_dir():
        out_dir.mkdir(parents=True, exist_ok=True)
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path in sorted(raw_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        msgs = data.get("messages", [])
        if not isinstance(msgs, list):
            continue
        lines = lines_from_stored_messages(msgs)
        text = "\n".join(lines)
        if text:
            text += "\n"
        out_path = out_dir / f"{path.stem}.txt"
        out_path.write_text(text, encoding="utf-8")
        written.append(out_path)
    return written


def main() -> None:
    export_raw_logs_to_txt()


if __name__ == "__main__":
    main()
