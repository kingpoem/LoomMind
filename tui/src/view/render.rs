use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::prelude::*;
use ratatui::style::Modifier;
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

use crate::session::state::{App, Overlay, SessionState};
use crate::theme::constants::{COMPOSER_HEIGHT, POPUP_AREA_HEIGHT, SPINNER_FRAMES, STATUS_HEIGHT};
use crate::theme::palette;
use crate::util::{directory_line, truncate_left_to_width, truncate_to_width};
use crate::view::history::render_buffer_line;
use crate::view::popup::{
    render_selector, render_slash_popup, render_tool_approval, render_trust_approval, SlashPopup,
};

pub fn draw_inline(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(COMPOSER_HEIGHT),
            Constraint::Length(POPUP_AREA_HEIGHT),
            Constraint::Length(STATUS_HEIGHT),
        ])
        .split(area);

    render_composer(frame, chunks[0], app);

    match &app.overlay {
        Overlay::Selector(sel) => render_selector(frame, chunks[1], sel),
        Overlay::Approval(req) => render_tool_approval(frame, chunks[1], req),
        Overlay::Trust(req) => render_trust_approval(frame, chunks[1], req),
        Overlay::None if SlashPopup::is_active(&app.input) => {
            render_slash_popup(frame, chunks[1], &app.input, &app.popup);
        }
        Overlay::None if app.state == SessionState::Working => {
            render_streaming_preview(frame, chunks[1], app);
        }
        _ => {}
    }

    render_status_bar(frame, chunks[2], app);
}

fn render_streaming_preview(frame: &mut Frame, zone: Rect, app: &App) {
    let width = zone.width as usize;
    for row in 0..zone.height {
        let blank = Line::from(Span::raw(" ".repeat(width)));
        render_buffer_line(frame, zone.y + row, &blank, zone.width, zone.x);
    }
    if zone.height == 0 || zone.width == 0 {
        return;
    }

    let title = Line::from(vec![
        Span::styled("• ", Style::default().fg(palette::DIM)),
        Span::styled("助手（流式输出）", Style::default().fg(palette::DIM)),
    ]);
    render_buffer_line(frame, zone.y, &title, zone.width, zone.x);

    let content_width = width.saturating_sub(2).max(1);
    let content_lines = if app.assistant_buf.is_empty() {
        vec!["等待模型输出…".to_string()]
    } else {
        wrap_for_preview(&app.assistant_buf, content_width)
    };

    let max_visible = zone.height.saturating_sub(1) as usize;
    let start = content_lines.len().saturating_sub(max_visible);
    for (idx, seg) in content_lines[start..].iter().enumerate() {
        let y = zone.y + 1 + idx as u16;
        let line = Line::from(vec![
            Span::raw("  "),
            Span::styled(seg.clone(), Style::default().fg(palette::FG)),
        ]);
        render_buffer_line(frame, y, &line, zone.width, zone.x);
    }
}

fn wrap_for_preview(text: &str, max_width: usize) -> Vec<String> {
    if max_width == 0 {
        return vec![text.to_string()];
    }
    let mut out = Vec::new();
    for raw_line in text.split('\n') {
        if raw_line.is_empty() {
            out.push(String::new());
            continue;
        }
        let mut current = String::new();
        let mut current_w = 0usize;
        for ch in raw_line.chars() {
            let cw = UnicodeWidthChar::width(ch).unwrap_or(0);
            if current_w + cw > max_width && !current.is_empty() {
                out.push(std::mem::take(&mut current));
                current_w = 0;
            }
            current.push(ch);
            current_w += cw;
        }
        if !current.is_empty() {
            out.push(current);
        }
    }
    out
}

fn render_composer(frame: &mut Frame, zone: Rect, app: &App) {
    let width = zone.width.max(2) as usize;
    let bg = Style::default()
        .bg(palette::USER_BAR_BG)
        .fg(palette::USER_BAR_FG);
    let placeholder = "向 LoomMind 提问，回车发送…";
    let content_y = zone.y + 1.min(zone.height.saturating_sub(1));

    let body_text = if app.input.is_empty() {
        Span::styled(placeholder, bg.add_modifier(Modifier::DIM))
    } else {
        let visible = truncate_to_width(&app.input, width.saturating_sub(2));
        Span::styled(visible, bg)
    };

    let body_w = body_text.content.width();
    let trailing_pad = width.saturating_sub(2 + body_w);

    let row = Line::from(vec![
        Span::styled("› ", bg.add_modifier(Modifier::BOLD)),
        body_text,
        Span::styled(" ".repeat(trailing_pad), bg),
    ]);

    let blank = Line::from(Span::styled(" ".repeat(width), bg));
    render_buffer_line(frame, zone.y, &blank, zone.width, zone.x);
    render_buffer_line(frame, content_y, &row, zone.width, zone.x);
    if zone.height > 2 {
        render_buffer_line(frame, zone.y + 2, &blank, zone.width, zone.x);
    }

    let prefix_cells = 2usize;
    let before = &app.input[..app.cursor.min(app.input.len())];
    let cursor_col = zone.x as usize + prefix_cells + before.width();
    let max_col = zone.x as usize + width.saturating_sub(1);
    let cursor_col = cursor_col.min(max_col) as u16;
    frame.set_cursor_position((cursor_col, content_y));
}

fn render_status_bar(frame: &mut Frame, zone: Rect, app: &App) {
    let dir = directory_line();

    let mut left_spans: Vec<Span<'static>> = Vec::new();
    if app.state == SessionState::Working {
        let frame_ch = SPINNER_FRAMES[app.spinner_idx % SPINNER_FRAMES.len()];
        left_spans.push(Span::styled(
            format!("{frame_ch} "),
            Style::default().fg(palette::SELECTED),
        ));
    }
    left_spans.push(Span::styled(
        format!("{} ", app.model_label),
        Style::default().fg(palette::FG),
    ));
    left_spans.push(Span::styled(
        format!("· {}", app.status),
        Style::default().fg(palette::DIM),
    ));

    let token_str = app
        .last_token_usage
        .map(|(used, limit)| format!("{used} / {limit} tok"))
        .unwrap_or_default();

    let tail_segments = vec![format!("{}", dir), token_str];
    let tail = tail_segments
        .into_iter()
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join("  ·  ");

    let left_line = Line::from(left_spans);
    let used_left = left_line.width();

    let zone_w = zone.width as usize;
    let avail_for_tail = zone_w.saturating_sub(used_left + 2);
    let tail_shown = if tail.width() > avail_for_tail {
        truncate_left_to_width(&tail, avail_for_tail)
    } else {
        tail
    };
    let pad = zone_w.saturating_sub(used_left + tail_shown.width()).max(1);

    let mut spans = left_line.spans;
    spans.push(Span::raw(" ".repeat(pad)));
    spans.push(Span::styled(tail_shown, Style::default().fg(palette::DIM)));

    render_buffer_line(frame, zone.y, &Line::from(spans), zone.width, zone.x);
}
