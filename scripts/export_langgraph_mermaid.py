"""扫描源码中的 LangGraph StateGraph 构建调用，生成 Mermaid 流程图。

输出为带 ```mermaid 代码块的 Markdown，便于 VS Code / Cursor 内置 Markdown 预览
配合 Mermaid 扩展（如 Markdown Preview Mermaid Support）直接渲染。

通过 AST 解析 `.add_node` / `.add_edge` / `.add_conditional_edges`；
若项目后续改为工厂函数封装，可把扫描根目录扩到对应包路径或改为显式入口文件列表。
"""

import argparse
import ast
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GraphExtraction:
    """单次扫描的边与节点（跨文件合并时使用）。"""

    nodes: set[str] = field(default_factory=set)
    edges: list[tuple[str, str, str | None]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


_START_IDS = frozenset({"START", "__start__"})
_END_IDS = frozenset({"END", "__end__"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _py_files(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def _endpoint_from_expr(expr: ast.expr | None) -> str | None:
    if expr is None:
        return None
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name):
        if expr.id in _START_IDS:
            return "__start__"
        if expr.id in _END_IDS:
            return "__end__"
        return expr.id
    return None


def _first_add_node_arg(call: ast.Call) -> ast.expr | None:
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == "node":
            return kw.value
    return None


def _conditional_path_map(call: ast.Call) -> ast.Dict | None:
    """add_conditional_edges(source, path, path_map) — 取第三个位置参数或 path_map=。"""
    if len(call.args) >= 3 and isinstance(call.args[2], ast.Dict):
        return call.args[2]
    for kw in call.keywords:
        if kw.arg == "path_map" and isinstance(kw.value, ast.Dict):
            return kw.value
    return None


def _dict_key_str(k: ast.expr | None) -> str | None:
    if k is None:
        return None
    if isinstance(k, ast.Constant) and isinstance(k.value, str):
        return k.value
    return None


def extract_from_source(source: str, *, rel_path: str) -> GraphExtraction:
    out = GraphExtraction(sources=[rel_path])
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr == "add_node":
            arg0 = _first_add_node_arg(node)
            nid = _endpoint_from_expr(arg0)
            if nid and nid not in _START_IDS and nid not in _END_IDS:
                out.nodes.add(nid)
        elif func.attr == "add_edge":
            if len(node.args) < 2:
                continue
            s, t = _endpoint_from_expr(node.args[0]), _endpoint_from_expr(node.args[1])
            if s and t:
                out.edges.append((s, t, None))
        elif func.attr == "add_conditional_edges":
            if not node.args:
                continue
            src = _endpoint_from_expr(node.args[0])
            if not src:
                continue
            pm = _conditional_path_map(node)
            if pm is None:
                out.edges.append((src, "?", "conditional"))
                continue
            for k, v in zip(pm.keys, pm.values, strict=False):
                label = _dict_key_str(k)
                dst = _endpoint_from_expr(v)
                if dst:
                    out.edges.append((src, dst, label))

    return out


def _merge_extractions(parts: list[GraphExtraction]) -> GraphExtraction:
    merged = GraphExtraction()
    seen_edges: set[tuple[str, str, str | None]] = set()
    for p in parts:
        merged.sources.extend(p.sources)
        merged.nodes |= p.nodes
        for e in p.edges:
            if e not in seen_edges:
                seen_edges.add(e)
                merged.edges.append(e)
    # 出现在边里但未被 add_node 显式声明的节点（如仅通过边引用）
    for s, t, _ in merged.edges:
        for x in (s, t):
            if x not in ("?",):
                merged.nodes.add(x)
    merged.nodes.discard("__start__")
    merged.nodes.discard("__end__")
    merged.nodes.discard("?")
    return merged


def _mermaid_safe_id(name: str) -> str:
    """Mermaid 节点 id：字母数字与下划线；数字开头则加前缀。"""
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    if not safe:
        return "node_unknown"
    if safe[0].isdigit():
        return f"n_{safe}"
    return safe


def _mermaid_label(edge_label: str | None) -> str:
    if not edge_label:
        return ""
    escaped = edge_label.replace('"', "#quot;")
    return f' | "{escaped}"'


def build_markdown(merged: GraphExtraction) -> str:
    """生成含 Mermaid 代码块的 Markdown（唯一产物格式）。"""
    lines: list[str] = [
        "flowchart TD",
        '  __start__(["START"])',
        '  __end__(["END"])',
    ]
    for n in sorted(merged.nodes):
        mid = _mermaid_safe_id(n)
        lines.append(f'  {mid}["{n}"]')
    need_unknown = any(t == "?" for _, t, _ in merged.edges)
    if need_unknown:
        lines.append('  unknown_next["?"]')
    for s, t, el in merged.edges:
        sid = _mermaid_safe_id(s) if s not in ("__start__", "__end__") else s
        if t == "?":
            tid = "unknown_next"
        elif t in ("__start__", "__end__"):
            tid = t
        else:
            tid = _mermaid_safe_id(t)
        lbl = _mermaid_label(el)
        lines.append(f"  {sid} -->{lbl} {tid}")
    diagram = "\n".join(lines).rstrip() + "\n"

    sources = sorted(set(merged.sources))
    src_line = f"Sources: {', '.join(sources)}\n" if sources else ""
    banner = (
        "<!--\n"
        "  Generated by scripts/export_langgraph_mermaid.py\n"
        f"  {src_line}"
        "  Regenerate: make graph\n"
        "-->\n\n"
        "# LangGraph\n\n"
    )
    return f"{banner}```mermaid\n{diagram}```\n"


def scan_roots(roots: list[Path]) -> GraphExtraction:
    parts: list[GraphExtraction] = []
    for root in roots:
        r = root.resolve()
        for py in _py_files(r):
            rel = (
                str(py.relative_to(_repo_root()))
                if py.is_relative_to(_repo_root())
                else str(py)
            )
            text = py.read_text(encoding="utf-8")
            ext = extract_from_source(text, rel_path=rel)
            if ext.edges or ext.nodes:
                parts.append(ext)
    return _merge_extractions(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="从源码导出 LangGraph 结构为 Mermaid")
    ap.add_argument(
        "--roots",
        type=Path,
        nargs="*",
        default=None,
        help="要扫描的目录（默认: 仓库下 src）",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="输出 .md 路径（默认: data/langgraph.md）",
    )
    args = ap.parse_args()
    repo = _repo_root()
    roots = [repo / "src"] if args.roots is None else list(args.roots)
    out_path = args.output or (repo / "data" / "langgraph.md")
    merged = scan_roots(roots)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_markdown(merged), encoding="utf-8")
    print(f"Wrote {out_path.relative_to(repo)}")


if __name__ == "__main__":
    main()
