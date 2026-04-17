"""memory ↔ context：把概述与手册节选注入系统提示。"""

from .store import read_handbook, read_memory_summary


def build_system_prompt_with_memory(
    core_prompt: str,
    *,
    handbook_max_chars: int = 3500,
) -> str:
    """在核心系统提示后附加概述与手册节选（见仓库 memory/）。"""
    parts: list[str] = [core_prompt.rstrip()]
    summary = read_memory_summary()
    if summary:
        parts.append("\n\n## 长期记忆（概述）\n" + summary)
    handbook = read_handbook(max_chars=handbook_max_chars)
    if handbook:
        parts.append("\n\n## 长期记忆（手册节选）\n" + handbook)
    return "\n".join(parts).strip()
