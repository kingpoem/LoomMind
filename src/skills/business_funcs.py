"""业务函数实现层（不绑定 LangChain Tool）。

这里的函数只负责“把输入变成输出”，不包含任何工具声明/元数据。
工具的 name/description/选择哪些函数暴露给 LLM，统一由 `skills_config.json`
和 `loader.py` 负责，从而实现“声明（JSON）”与“实现（Python）”解耦。

约束：
- 请务必写清楚函数签名的类型注解（LangChain 会据此推导参数 schema）。
- 返回值尽量使用 str / dict / list 等可 JSON 序列化的类型，便于模型理解与编排。
"""

from pathlib import Path
from typing import Any


def pdf_info(path: str) -> dict[str, Any]:
    """读取 PDF 的基础信息（页数、标题等元数据）。"""

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as e:
        raise RuntimeError("缺少依赖：pypdf。请先安装/同步项目依赖后再使用 pdf_* skills。") from e

    p = Path(path)
    reader = PdfReader(str(p))
    meta = reader.metadata or {}
    # pypdf metadata keys are usually like "/Title"
    cleaned_meta: dict[str, Any] = {
        str(k).lstrip("/"): (str(v) if v is not None else "")
        for k, v in dict(meta).items()
    }
    return {
        "path": str(p),
        "pages": len(reader.pages),
        "metadata": cleaned_meta,
    }


def pdf_to_text(path: str, max_pages: int | None = 10) -> str:
    """从 PDF 提取文本（默认最多前 10 页，避免输出过长）。"""

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as e:
        raise RuntimeError("缺少依赖：pypdf。请先安装/同步项目依赖后再使用 pdf_* skills。") from e

    p = Path(path)
    reader = PdfReader(str(p))
    total = len(reader.pages)
    n = total if max_pages is None else max(0, min(int(max_pages), total))

    parts: list[str] = []
    for i in range(n):
        page = reader.pages[i]
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text.strip())

    return "\n\n".join(parts)

