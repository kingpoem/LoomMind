"""memory ↔ context：把概述与手册节选注入系统提示。"""

import trust

from .store import read_handbook, read_memory_summary


def build_system_prompt_with_memory(
    core_prompt: str,
    *,
    handbook_max_chars: int = 3500,
) -> str:
    """在核心系统提示后附加概述与手册节选（见仓库 memory/）。

    若当前会话处于信任态，额外附加工作区绝对路径，提示模型可直接读取。
    """
    parts: list[str] = [core_prompt.rstrip()]
    if trust.is_trusted():
        parts.append(
            f"\n\n## 工作区\n当前绝对路径：{trust.workspace_root()}\n"
            # "你可直接读取该目录下的文件，不需要为每次读取重复征询用户。"
        )
    summary = read_memory_summary()
    if summary:
        parts.append("\n\n## 长期记忆（概述）\n" + summary)
    handbook = read_handbook(max_chars=handbook_max_chars)
    if handbook:
        parts.append("\n\n## 长期记忆（手册节选）\n" + handbook)
    return "\n".join(parts).strip()
