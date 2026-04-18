"""飞书长连接：接收消息（机器人会话事件），以用户身份发回复。"""

import json
import logging
import os
import threading
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from lark_oapi import Client
from lark_oapi.api.im.v1.model.create_message_request import CreateMessageRequest
from lark_oapi.api.im.v1.model.create_message_request_body import (
    CreateMessageRequestBody,
)
from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1
from lark_oapi.core.enum import LogLevel
from lark_oapi.core.model import RequestOption
from lark_oapi.event.custom import CustomizedEvent
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.ws.client import Client as WSClient

import trust
from context.content_manager import ContentManager
from graph_agent import build_graph
from memory import build_system_prompt_with_memory

logger = logging.getLogger(__name__)

_CORE_SYSTEM_PROMPT = "你是简洁助手，用中文回答。"

_chat_lock = threading.Lock()
_chat_sessions: dict[str, tuple[list[BaseMessage], ContentManager]] = {}


def _env(name: str, *, required: bool = True) -> str:
    v = os.environ.get(name, "").strip()
    if required and not v:
        msg = f"缺少环境变量 {name}"
        raise RuntimeError(msg)
    return v


def _chat_id(message: Any) -> str | None:
    if message is None:
        return None
    if isinstance(message, dict):
        return message.get("chat_id")
    return getattr(message, "chat_id", None)


def _extract_text(message: Any) -> str | None:
    if message is None:
        return None
    msg_type = (
        message.get("message_type")
        if isinstance(message, dict)
        else getattr(message, "message_type", None)
    )
    content = (
        message.get("content")
        if isinstance(message, dict)
        else getattr(message, "content", None)
    )
    if msg_type != "text" or not content:
        return None
    try:
        return str(json.loads(content).get("text", "")).strip()
    except (json.JSONDecodeError, TypeError):
        return None


def _sender_open_id(sender: Any) -> str | None:
    if sender is None:
        return None
    sid = (
        sender.get("sender_id")
        if isinstance(sender, dict)
        else getattr(sender, "sender_id", None)
    )
    if sid is None:
        return None
    if isinstance(sid, dict):
        return sid.get("open_id")
    return getattr(sid, "open_id", None)


def _session_for_chat(chat_id: str) -> tuple[list[BaseMessage], ContentManager]:
    with _chat_lock:
        entry = _chat_sessions.get(chat_id)
        if entry is None:
            manager = ContentManager()
            msgs: list[BaseMessage] = [
                SystemMessage(
                    content=build_system_prompt_with_memory(_CORE_SYSTEM_PROMPT)
                ),
            ]
            manager.persist(msgs)
            _chat_sessions[chat_id] = (msgs, manager)
            return msgs, manager
        return entry


def _reply_text_from_graph(graph, chat_id: str, user_text: str) -> str:
    messages, manager = _session_for_chat(chat_id)
    messages.append(HumanMessage(content=user_text))
    try:
        result = graph.invoke({"messages": messages})
    except Exception:
        manager.persist(messages)
        raise
    messages[:] = list(result["messages"])
    manager.persist(messages)
    last = messages[-1]
    if isinstance(last, AIMessage):
        c = last.content
        return c if isinstance(c, str) else str(c)
    return str(last)


def _send_text_as_user(
    client: Client,
    user_access_token: str,
    chat_id: str,
    text: str,
) -> None:
    body = (
        CreateMessageRequestBody.builder()
        .receive_id(chat_id)
        .msg_type("text")
        .content(json.dumps({"text": text}, ensure_ascii=False))
        .build()
    )
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(body)
        .build()
    )
    opt = RequestOption()
    opt.user_access_token = user_access_token
    resp = client.im.v1.message.create(req, opt)
    if resp.code != 0:
        logger.error(
            "发送消息失败 code=%s msg=%s", resp.code, getattr(resp, "msg", resp)
        )


def _process_incoming(
    message: Any,
    sender: Any,
    *,
    graph,
    client: Client,
    user_access_token: str,
    self_open_id: str | None,
) -> None:
    try:
        if self_open_id and _sender_open_id(sender) == self_open_id:
            return
        chat_id = _chat_id(message)
        if not chat_id:
            return
        text = _extract_text(message)
        if not text:
            logger.info("跳过非文本或空消息")
            return
        reply = _reply_text_from_graph(graph, chat_id, text)
        if not reply:
            return
        if not user_access_token:
            logger.warning("跳过发送：未配置 FEISHU_USER_ACCESS_TOKEN")
            return
        _send_text_as_user(client, user_access_token, chat_id, reply)
    except Exception:
        logger.exception("处理飞书消息失败")


def _on_p2_im_receive(
    data: P2ImMessageReceiveV1,
    *,
    graph,
    client: Client,
    user_access_token: str,
    self_open_id: str | None,
) -> None:
    ev = data.event
    if ev is None:
        return
    _process_incoming(
        ev.message,
        ev.sender,
        graph=graph,
        client=client,
        user_access_token=user_access_token,
        self_open_id=self_open_id,
    )


def _on_p2_im_receive_custom(
    data: CustomizedEvent,
    *,
    graph,
    client: Client,
    user_access_token: str,
    self_open_id: str | None,
) -> None:
    ev = data.event
    if not isinstance(ev, dict):
        return
    _process_incoming(
        ev.get("message"),
        ev.get("sender"),
        graph=graph,
        client=client,
        user_access_token=user_access_token,
        self_open_id=self_open_id,
    )


def _spawn_handler(fn, *args, **kwargs) -> None:
    """避免阻塞 lark WS 的 asyncio 循环（心跳等）。"""

    def _run() -> None:
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception("飞书消息后台任务异常")

    threading.Thread(target=_run, daemon=True).start()


def build_event_dispatcher(
    *,
    encrypt_key: str,
    verification_token: str,
    graph,
    client: Client,
    user_access_token: str,
    self_open_id: str | None,
) -> EventDispatcherHandler:
    def p2_handler(data: P2ImMessageReceiveV1) -> None:
        _spawn_handler(
            _on_p2_im_receive,
            data,
            graph=graph,
            client=client,
            user_access_token=user_access_token,
            self_open_id=self_open_id,
        )

    def p2_custom(data: CustomizedEvent) -> None:
        _spawn_handler(
            _on_p2_im_receive_custom,
            data,
            graph=graph,
            client=client,
            user_access_token=user_access_token,
            self_open_id=self_open_id,
        )

    return (
        EventDispatcherHandler.builder(encrypt_key, verification_token, LogLevel.INFO)
        .register_p2_im_message_receive_v1(p2_handler)
        .register_p2_customized_event("im.message.receive_v2", p2_custom)
        .build()
    )


def run_feishu_long_connection() -> None:
    """使用飞书事件长连接：需在开放平台将事件订阅方式配置为「长连接」。"""
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # 飞书是长驻 bot，没有启动时可交互的用户，显式禁用工作区信任态。
    trust.set_trusted(False)

    app_id = _env("FEISHU_APP_ID")
    app_secret = _env("FEISHU_APP_SECRET")
    verification_token = _env("FEISHU_VERIFICATION_TOKEN")
    user_access_token = os.environ.get("FEISHU_USER_ACCESS_TOKEN", "").strip()
    encrypt_key = os.environ.get("FEISHU_ENCRYPT_KEY", "").strip()
    self_open_id = os.environ.get("FEISHU_USER_OPEN_ID", "").strip() or None

    graph = build_graph()
    client = (
        Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .enable_set_token(True)
        .build()
    )

    dispatcher = build_event_dispatcher(
        encrypt_key=encrypt_key,
        verification_token=verification_token,
        graph=graph,
        client=client,
        user_access_token=user_access_token,
        self_open_id=self_open_id,
    )

    logger.info("启动飞书长连接，等待消息…")
    ws = WSClient(app_id, app_secret, log_level=LogLevel.INFO, event_handler=dispatcher)
    ws.start()
