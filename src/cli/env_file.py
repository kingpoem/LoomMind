"""读写项目根目录 `.env`（用于 TUI 持久化 API 等配置）。"""

import re
from pathlib import Path

_LINE_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$",
)


def parse_dotenv(path: Path) -> dict[str, str]:
    """解析 KEY=value，忽略注释与空行；值去掉首尾引号。"""
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(raw)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        quoted = (v.startswith('"') and v.endswith('"')) or (
            v.startswith("'") and v.endswith("'")
        )
        if quoted:
            v = v[1:-1]
        out[k] = v
    return out


def _escape_value(val: str) -> str:
    if re.search(r'[\s=#"\']', val):
        esc = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{esc}"'
    return val


def upsert_dotenv(path: Path, key: str, value: str) -> None:
    """写入或更新一行 `KEY=value`，保留其余行顺序。"""
    key = key.strip()
    if not key:
        raise ValueError("env key 不能为空")
    new_line = f"{key}={_escape_value(value)}\n"
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        lines = []
    pat = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=")
    replaced = False
    out: list[str] = []
    for line in lines:
        if pat.match(line):
            out.append(new_line)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"
        out.append(new_line)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(out), encoding="utf-8")


def remove_dotenv_key(path: Path, key: str) -> None:
    """删除 `KEY=` 行（若存在）。"""
    if not path.is_file():
        return
    pat = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [ln for ln in lines if not pat.match(ln)]
    path.write_text("".join(kept), encoding="utf-8")
