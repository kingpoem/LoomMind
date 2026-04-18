"""从仓库根 `template/prompts/` 加载预置提示词（UTF-8）。

子目录约定：`compass/`（会话压缩）、`core/`（入口核心 system）、`planning/`（规划循环）。
"""

from functools import lru_cache

from settings import repo_root


@lru_cache
def load_template_prompt(relative_path: str) -> str:
    """读取 `template/prompts/<relative_path>`，剔除首尾空白。

    例：`compass/summary_system.txt`、`core/system.txt`。
    """
    path = repo_root() / "template" / "prompts" / relative_path
    return path.read_text(encoding="utf-8").strip()
