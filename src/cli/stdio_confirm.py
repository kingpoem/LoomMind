"""stdio 模式下工具交互：把确认请求与调用通知以 NDJSON 发给 TUI。"""

import json
import logging
import uuid

from trust import TrustCategory

from .stdio_protocol import emit, read_command_line

logger = logging.getLogger(__name__)

# 工具类别 → 给用户看的中文权限说明。取代旧的 per-tool 硬编码表，
# 以 `tools/server.py :: tool_category` 登记的 TrustCategory 为唯一来源。
_CATEGORY_HINTS: dict[TrustCategory, str] = {
    TrustCategory.READ_FS: "读取本地文件",
    TrustCategory.WRITE_FS: "写入本地文件",
    TrustCategory.EXEC: "执行系统命令",
    TrustCategory.NETWORK: "访问网络",
}


def _permissions_for(tool_name: str) -> list[str]:
    # 延迟导入：避免 cli 子模块在加载时强行把 tools.server 拉起来。
    from tools.server import tool_category

    cat = tool_category(tool_name)
    if cat is None:
        return []
    hint = _CATEGORY_HINTS.get(cat)
    return [hint] if hint else []


def _preview_for(tool_name: str, args: dict) -> str | None:
    """查询工具登记的 preview 函数并运行；缺省或异常都返回 None。"""
    from tools.server import tool_preview

    fn = tool_preview(tool_name)
    if fn is None:
        return None
    try:
        text = fn(args)
    except Exception:
        logger.exception("工具 %s 预览执行失败", tool_name)
        return None
    if not text or not isinstance(text, str):
        return None
    return text


def _safe_args(args: dict) -> dict:
    """把 args 转成可 JSON 序列化的形式；无法序列化的对象 fallback 为 str。"""
    return json.loads(json.dumps(args, ensure_ascii=False, default=str))


def stdio_tool_confirm(tool_name: str, args: dict) -> bool:
    req_id = uuid.uuid4().hex
    safe_args = _safe_args(args)
    payload: dict = {
        "type": "tool_confirm_request",
        "id": req_id,
        "tool": tool_name,
        "args": safe_args,
        "permissions": _permissions_for(tool_name),
    }
    preview = _preview_for(tool_name, args)
    if preview is not None:
        payload["preview"] = preview
    emit(payload)
    while True:
        raw = read_command_line()
        if raw is None:
            return False
        if not raw:
            continue
        cmd = raw.get("type")
        if cmd == "tool_confirm_response" and raw.get("id") == req_id:
            return bool(raw.get("approved"))
        if cmd == "shutdown":
            return False
        logger.warning("等待工具确认时收到未处理指令: %s", cmd)


def stdio_tool_notify(tool_name: str, args: dict) -> None:
    """每次真正调用工具前发一条事件，让 TUI 向用户展示"正在使用工具 X"。

    与 tool_confirm_request 互补：自动放行（信任态下的 READ_FS 等）或用户
    刚点过"允许"的情况，都会触发这条通知。
    """
    emit(
        {
            "type": "tool_invoked",
            "tool": tool_name,
            "args": _safe_args(args),
        }
    )
