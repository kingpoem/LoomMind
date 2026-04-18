use std::io;
use std::process::ChildStdin;
use std::time::Instant;

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use serde_json::json;

use crate::child::{send_command, ChildEvent};
use crate::session::input::{backspace, delete_forward, insert_char, move_left, move_right};
use crate::session::state::{App, Overlay, SessionState};
use crate::term::Term;
use crate::util::{normalize_inline_text, truncate_to_width};
use crate::view::history::{insert_assistant, insert_error, insert_system, insert_user};
use crate::view::popup::{Selector, SelectorKind, SlashPopup, ToolApproval, TrustApproval};

pub fn handle_child_event(term: &mut Term, app: &mut App, ev: ChildEvent) -> io::Result<()> {
    match ev {
        ChildEvent::Ready { message, model } => {
            app.status = if message.is_empty() {
                "已就绪".into()
            } else {
                message
            };
            if let Some(m) = model {
                if !m.is_empty() {
                    app.model_label = m;
                }
            }
            app.state = SessionState::Idle;
        }
        ChildEvent::System(msg) => {
            insert_system(term, &msg)?;
        }
        ChildEvent::AssistantDelta(text) => {
            app.state = SessionState::Working;
            let cleaned = normalize_inline_text(&text);
            app.assistant_buf.push_str(&cleaned);
            app.status = "生成中…".into();
        }
        ChildEvent::AssistantMessage(text) => {
            if app.assistant_buf.is_empty() {
                let cleaned = normalize_inline_text(&text);
                app.assistant_buf.push_str(&cleaned);
            }
        }
        ChildEvent::TokenUsage { used, limit } => {
            app.last_token_usage = Some((used, limit));
            if !app.assistant_buf.is_empty() {
                let buf = std::mem::take(&mut app.assistant_buf);
                insert_assistant(term, &buf)?;
            }
            app.state = SessionState::Idle;
            app.status = "就绪".into();
        }
        ChildEvent::Error(msg) => {
            insert_error(term, &msg)?;
            app.state = SessionState::Idle;
        }
        ChildEvent::SessionEnd(reason) => {
            insert_system(term, &format!("会话结束（{reason}）"))?;
            app.quit = true;
        }
        ChildEvent::ProcessExited => {
            insert_system(term, "Python 子进程已退出。")?;
            app.quit = true;
        }
        ChildEvent::Models { items, current } => {
            if let Overlay::Selector(sel) = &mut app.overlay {
                if sel.kind == SelectorKind::Model {
                    let selected = current.clone().map(|c| vec![c]).unwrap_or_default();
                    sel.populate(items, selected);
                    return Ok(());
                }
            }
            insert_system(term, &format!("当前模型：{}", current.unwrap_or_default()))?;
            insert_system(term, &format!("可用模型：{}", items.join(", ")))?;
        }
        ChildEvent::Skills { items, selected } => {
            if let Overlay::Selector(sel) = &mut app.overlay {
                if sel.kind == SelectorKind::Skills {
                    sel.populate(items, selected);
                    return Ok(());
                }
            }
        }
        ChildEvent::Mcps { items, selected } => {
            if let Overlay::Selector(sel) = &mut app.overlay {
                if sel.kind == SelectorKind::Mcp {
                    sel.populate(items, selected);
                    return Ok(());
                }
            }
        }
        ChildEvent::ModelSet(name) => {
            app.model_label = name.clone();
            insert_system(term, &format!("已切换模型为 {name}"))?;
        }
        ChildEvent::SkillsSet(names) => {
            let msg = if names.is_empty() {
                "已禁用全部 skills".to_string()
            } else {
                format!("已启用 skills：{}", names.join(", "))
            };
            insert_system(term, &msg)?;
        }
        ChildEvent::McpsSet(names) => {
            let msg = if names.is_empty() {
                "已禁用全部 MCP 工具".to_string()
            } else {
                format!("已启用 MCP：{}", names.join(", "))
            };
            insert_system(term, &msg)?;
        }
        ChildEvent::ToolConfirmRequest {
            id,
            tool,
            args,
            permissions,
            preview,
        } => {
            // 先让历史把此前缓冲的助手流落盘，后面的系统行才能按真实时序排列。
            if !app.assistant_buf.is_empty() {
                let buf = std::mem::take(&mut app.assistant_buf);
                insert_assistant(term, &buf)?;
            }
            app.overlay = Overlay::Approval(ToolApproval::new(id, tool.clone(), args, permissions));
            app.status = "等待工具授权…".into();
            insert_system(term, &format!("工具 {tool} 请求执行权限，请确认。"))?;
            if let Some(body) = preview {
                for line in body.split('\n') {
                    if line.is_empty() {
                        continue;
                    }
                    insert_system(term, line)?;
                }
            }
        }
        ChildEvent::ToolInvoked { tool, args } => {
            // 先把正在缓冲的助手流内容落到历史，使系统行能按真实时间顺序出现。
            if !app.assistant_buf.is_empty() {
                let buf = std::mem::take(&mut app.assistant_buf);
                insert_assistant(term, &buf)?;
            }
            let brief = truncate_to_width(&args, 60);
            insert_system(term, &format!("正在使用工具 {tool}({brief})"))?;
        }
        ChildEvent::TrustRequest { workspace } => {
            app.overlay = Overlay::Trust(TrustApproval::new(workspace.clone()));
            app.status = "等待工作区信任决定…".into();
            insert_system(term, &format!("请选择是否信任工作区：{workspace}"))?;
        }
    }
    Ok(())
}

pub fn handle_key(
    term: &mut Term,
    app: &mut App,
    child_stdin: &mut ChildStdin,
    key: KeyEvent,
) -> io::Result<()> {
    if app.overlay.is_active() {
        return handle_overlay_key(term, app, child_stdin, key);
    }

    let popup_visible = SlashPopup::is_active(&app.input);

    if popup_visible {
        let items = SlashPopup::filtered(&app.input);
        let len = items.len();
        match (key.code, key.modifiers) {
            (KeyCode::Up, _) => {
                app.popup.move_up(len);
                return Ok(());
            }
            (KeyCode::Down, _) => {
                app.popup.move_down(len);
                return Ok(());
            }
            (KeyCode::Char(' '), _) => {
                if let Some(cmd) = app.popup.selected_command(&items) {
                    app.input = format!("/{}", cmd.name);
                    app.cursor = app.input.len();
                    app.refresh_popup();
                }
                return Ok(());
            }
            (KeyCode::Tab, _) => {
                if let Some(cmd) = app.popup.selected_command(&items) {
                    app.input = format!("/{}", cmd.name);
                    app.cursor = app.input.len();
                    app.refresh_popup();
                }
                return Ok(());
            }
            (KeyCode::Esc, _) => {
                app.input.clear();
                app.cursor = 0;
                app.refresh_popup();
                return Ok(());
            }
            (KeyCode::Enter, _) => {
                if let Some(cmd) = app.popup.selected_command(&items) {
                    app.input = format!("/{}", cmd.name);
                    app.cursor = app.input.len();
                }
                submit(term, app, child_stdin)?;
                return Ok(());
            }
            _ => {}
        }
    }

    match (key.code, key.modifiers) {
        (KeyCode::Char('c'), KeyModifiers::CONTROL)
        | (KeyCode::Char('d'), KeyModifiers::CONTROL) => {
            request_quit(child_stdin);
            app.quit = true;
        }
        (KeyCode::Esc, _) if app.input.is_empty() => {
            request_quit(child_stdin);
            app.quit = true;
        }
        (KeyCode::Esc, _) => {
            app.input.clear();
            app.cursor = 0;
            app.refresh_popup();
        }
        (KeyCode::Enter, _) => submit(term, app, child_stdin)?,
        (KeyCode::Backspace, _) => {
            backspace(app);
            app.refresh_popup();
        }
        (KeyCode::Delete, _) => {
            delete_forward(app);
            app.refresh_popup();
        }
        (KeyCode::Left, _) => move_left(app),
        (KeyCode::Right, _) => move_right(app),
        (KeyCode::Home, _) => app.cursor = 0,
        (KeyCode::End, _) => app.cursor = app.input.len(),
        (KeyCode::Char(c), m) if !m.contains(KeyModifiers::CONTROL) => {
            insert_char(app, c);
            app.refresh_popup();
        }
        _ => {}
    }
    Ok(())
}

fn handle_overlay_key(
    term: &mut Term,
    app: &mut App,
    child_stdin: &mut ChildStdin,
    key: KeyEvent,
) -> io::Result<()> {
    match &app.overlay {
        Overlay::Selector(_) => handle_selector_key(term, app, child_stdin, key),
        Overlay::Approval(_) => handle_approval_key(term, app, child_stdin, key),
        Overlay::Trust(_) => handle_trust_key(term, app, child_stdin, key),
        Overlay::None => Ok(()),
    }
}

fn handle_selector_key(
    _term: &mut Term,
    app: &mut App,
    child_stdin: &mut ChildStdin,
    key: KeyEvent,
) -> io::Result<()> {
    let Overlay::Selector(sel) = &mut app.overlay else {
        return Ok(());
    };

    match (key.code, key.modifiers) {
        (KeyCode::Esc, _) | (KeyCode::Char('c'), KeyModifiers::CONTROL) => {
            app.overlay = Overlay::None;
            return Ok(());
        }
        (KeyCode::Up, _) => {
            sel.move_up();
            return Ok(());
        }
        (KeyCode::Char('k'), m) if !m.contains(KeyModifiers::CONTROL) => {
            sel.move_up();
            return Ok(());
        }
        (KeyCode::Down, _) => {
            sel.move_down();
            return Ok(());
        }
        (KeyCode::Char('j'), m) if !m.contains(KeyModifiers::CONTROL) => {
            sel.move_down();
            return Ok(());
        }
        (KeyCode::Char(' '), _) => {
            if sel.multi {
                sel.toggle();
            } else {
                let _ = sel.pick_single();
            }
            return Ok(());
        }
        (KeyCode::Enter, _) => {
            // 提交选择
            let kind = sel.kind;
            let payload = match kind {
                SelectorKind::Model => {
                    let pick = sel.pick_single();
                    pick.map(|name| json!({"type": "set_model", "name": name}))
                }
                SelectorKind::Skills => {
                    let names = sel.collect_selected();
                    Some(json!({"type": "set_skills", "names": names}))
                }
                SelectorKind::Mcp => {
                    let names = sel.collect_selected();
                    Some(json!({"type": "set_mcps", "names": names}))
                }
            };
            app.overlay = Overlay::None;
            if let Some(p) = payload {
                let _ = send_command(child_stdin, p);
            }
            return Ok(());
        }
        _ => {}
    }
    Ok(())
}

fn handle_approval_key(
    term: &mut Term,
    app: &mut App,
    child_stdin: &mut ChildStdin,
    key: KeyEvent,
) -> io::Result<()> {
    match (key.code, key.modifiers) {
        (KeyCode::Left, _) => {
            if let Overlay::Approval(req) = &mut app.overlay {
                req.move_left();
            }
            return Ok(());
        }
        (KeyCode::Right, _) | (KeyCode::Tab, _) => {
            if let Overlay::Approval(req) = &mut app.overlay {
                req.move_right();
            }
            return Ok(());
        }
        (KeyCode::Char(' '), _) => {
            if let Overlay::Approval(req) = &mut app.overlay {
                req.toggle();
            }
            return Ok(());
        }
        (KeyCode::Esc, _) | (KeyCode::Char('c'), KeyModifiers::CONTROL) => {
            submit_tool_approval(term, app, child_stdin, false)?;
            return Ok(());
        }
        (KeyCode::Enter, _) => {
            let approved = matches!(&app.overlay, Overlay::Approval(req) if req.approved());
            submit_tool_approval(term, app, child_stdin, approved)?;
            return Ok(());
        }
        _ => {}
    }
    Ok(())
}

fn handle_trust_key(
    term: &mut Term,
    app: &mut App,
    child_stdin: &mut ChildStdin,
    key: KeyEvent,
) -> io::Result<()> {
    match (key.code, key.modifiers) {
        (KeyCode::Left, _) => {
            if let Overlay::Trust(req) = &mut app.overlay {
                req.move_left();
            }
            return Ok(());
        }
        (KeyCode::Right, _) | (KeyCode::Tab, _) => {
            if let Overlay::Trust(req) = &mut app.overlay {
                req.move_right();
            }
            return Ok(());
        }
        (KeyCode::Char(' '), _) => {
            if let Overlay::Trust(req) = &mut app.overlay {
                req.toggle();
            }
            return Ok(());
        }
        (KeyCode::Esc, _) | (KeyCode::Char('c'), KeyModifiers::CONTROL) => {
            submit_trust_response(term, app, child_stdin, false)?;
            return Ok(());
        }
        (KeyCode::Enter, _) => {
            let trusted = matches!(&app.overlay, Overlay::Trust(req) if req.trusted());
            submit_trust_response(term, app, child_stdin, trusted)?;
            return Ok(());
        }
        _ => {}
    }
    Ok(())
}

fn submit_trust_response(
    term: &mut Term,
    app: &mut App,
    child_stdin: &mut ChildStdin,
    trusted: bool,
) -> io::Result<()> {
    if !matches!(&app.overlay, Overlay::Trust(_)) {
        return Ok(());
    }
    app.overlay = Overlay::None;
    let _ = send_command(
        child_stdin,
        json!({"type": "trust_response", "trust": trusted}),
    );
    if trusted {
        app.status = "已信任工作区".into();
        insert_system(term, "已信任AI访问当前工作区。")?;
    } else {
        app.status = "未信任工作区".into();
        insert_system(term, "未信任AI访问当前工作区。")?;
    }
    Ok(())
}

fn submit_tool_approval(
    term: &mut Term,
    app: &mut App,
    child_stdin: &mut ChildStdin,
    approved: bool,
) -> io::Result<()> {
    let Overlay::Approval(req) = &app.overlay else {
        return Ok(());
    };
    let req_id = req.id.clone();
    let tool = req.tool.clone();
    app.overlay = Overlay::None;
    let _ = send_command(
        child_stdin,
        json!({"type": "tool_confirm_response", "id": req_id, "approved": approved}),
    );
    if approved {
        app.status = "已授权，继续执行…".into();
        insert_system(term, &format!("已允许工具 {tool} 执行。"))?;
    } else {
        app.status = "已拒绝，等待模型继续…".into();
        insert_system(term, &format!("已拒绝工具 {tool} 执行。"))?;
    }
    Ok(())
}

fn open_selector(
    app: &mut App,
    child_stdin: &mut ChildStdin,
    kind: SelectorKind,
    title: &str,
    multi: bool,
    list_cmd: serde_json::Value,
) -> io::Result<()> {
    app.overlay = Overlay::Selector(Selector::new(kind, title, multi));
    send_command(child_stdin, list_cmd)
}

fn request_quit(child_stdin: &mut ChildStdin) {
    let _ = send_command(child_stdin, json!({"type": "shutdown"}));
}

fn submit(term: &mut Term, app: &mut App, child_stdin: &mut ChildStdin) -> io::Result<()> {
    if app.state == SessionState::Working {
        return Ok(());
    }
    let text = normalize_inline_text(app.input.trim());
    app.input.clear();
    app.cursor = 0;
    app.refresh_popup();
    if text.is_empty() {
        return Ok(());
    }

    if let Some(cmd) = text.strip_prefix('/') {
        let cmd = cmd.trim();
        let cmd_key = cmd.to_lowercase();
        match cmd_key.as_str() {
            "quit" | "exit" => {
                request_quit(child_stdin);
                app.quit = true;
                return Ok(());
            }
            "model" => {
                return open_selector(
                    app,
                    child_stdin,
                    SelectorKind::Model,
                    "选择模型",
                    false,
                    json!({"type": "list_models"}),
                );
            }
            "skills" => {
                return open_selector(
                    app,
                    child_stdin,
                    SelectorKind::Skills,
                    "启用 Skills（Space 切换）",
                    true,
                    json!({"type": "list_skills"}),
                );
            }
            "mcp" | "mcps" => {
                return open_selector(
                    app,
                    child_stdin,
                    SelectorKind::Mcp,
                    "启用 MCP（Space 切换）",
                    true,
                    json!({"type": "list_mcps"}),
                );
            }
            other => {
                insert_system(term, &format!("未知命令 /{other}"))?;
                return Ok(());
            }
        }
    }

    insert_user(term, &text)?;

    let payload = serde_json::json!({"type": "user_message", "text": text});
    if let Err(err) = send_command(child_stdin, payload) {
        insert_error(term, &format!("写入子进程失败: {err}"))?;
        app.quit = true;
        return Ok(());
    }
    app.state = SessionState::Working;
    app.status = "提交中…".into();
    app.spinner_idx = 0;
    app.spinner_last = Instant::now();
    Ok(())
}
