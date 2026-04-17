use std::io;

use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::prelude::*;
use ratatui::style::Modifier;
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

use crate::term::Term;
use crate::theme::palette;

/// 把一行 `Line` 写入 `Buffer` 指定行。
///
/// 直接走 `Buffer::set_line`，避免 `Paragraph` 在某些情况下
/// 对 CJK 宽字符产生的额外间距。
pub(crate) fn render_line(buf: &mut Buffer, y: u16, line: &Line<'_>, width: u16) {
    let _ = buf.set_line(0, y, line, width);
}

/// 渲染到 `Frame`（用于实时绘制阶段，与历史插入复用同一行写入逻辑）。
pub fn render_buffer_line(frame: &mut Frame, y: u16, line: &Line<'_>, width: u16, x: u16) {
    let area = Rect::new(x, y, width, 1);
    let buf = frame.buffer_mut();
    let _ = buf.set_line(area.x, area.y, line, area.width);
}

pub fn insert_user(term: &mut Term, text: &str) -> io::Result<()> {
    let width = term.size()?.width.max(20);
    let lines = build_user_lines(text, width);
    insert_lines(term, &lines, width)
}

pub fn insert_assistant(term: &mut Term, text: &str) -> io::Result<()> {
    let width = term.size()?.width.max(20);
    let lines = build_assistant_lines(text, width);
    insert_lines(term, &lines, width)
}

pub fn insert_system(term: &mut Term, text: &str) -> io::Result<()> {
    let width = term.size()?.width.max(20);
    let mut lines = vec![Line::from(vec![
        Span::styled("• ", Style::default().fg(palette::DIM)),
        Span::styled(text.to_string(), Style::default().fg(palette::DIM)),
    ])];
    lines.push(Line::from(""));
    insert_lines(term, &lines, width)
}

pub fn insert_error(term: &mut Term, text: &str) -> io::Result<()> {
    let width = term.size()?.width.max(20);
    let mut lines = vec![Line::from(vec![
        Span::styled("× ", Style::default().fg(palette::ERROR)),
        Span::styled(text.to_string(), Style::default().fg(palette::ERROR)),
    ])];
    lines.push(Line::from(""));
    insert_lines(term, &lines, width)
}

fn insert_lines(term: &mut Term, lines: &[Line<'static>], width: u16) -> io::Result<()> {
    let total = lines.len() as u16;
    if total == 0 {
        return Ok(());
    }
    term.insert_before(total, |buf| {
        for (i, l) in lines.iter().enumerate() {
            render_line(buf, i as u16, l, width);
        }
    })
}

fn build_user_lines(text: &str, width: u16) -> Vec<Line<'static>> {
    let inner_w = (width as usize).saturating_sub(2);
    let bg = Style::default()
        .bg(palette::USER_BAR_BG)
        .fg(palette::USER_BAR_FG);
    let mut out: Vec<Line<'static>> = Vec::new();

    out.push(blank_bg_line(width, bg));

    let lines = wrap_text(text, inner_w.max(1));
    for (i, seg) in lines.iter().enumerate() {
        let prefix_span = if i == 0 {
            Span::styled("› ", bg.add_modifier(Modifier::BOLD))
        } else {
            Span::styled("  ", bg)
        };
        let content_span = Span::styled(seg.clone(), bg);
        let used = 2 + UnicodeWidthStr::width(seg.as_str());
        let pad = (width as usize).saturating_sub(used);
        out.push(Line::from(vec![
            prefix_span,
            content_span,
            Span::styled(" ".repeat(pad), bg),
        ]));
    }
    out.push(blank_bg_line(width, bg));
    out.push(Line::from(""));
    out
}

fn blank_bg_line(width: u16, bg: Style) -> Line<'static> {
    Line::from(Span::styled(" ".repeat(width as usize), bg))
}

fn build_assistant_lines(text: &str, width: u16) -> Vec<Line<'static>> {
    let mut out = Vec::new();
    let wrapped = wrap_text(text, (width as usize).saturating_sub(2).max(1));
    for (i, seg) in wrapped.iter().enumerate() {
        if i == 0 {
            out.push(Line::from(vec![
                Span::styled("• ", Style::default().fg(palette::DIM)),
                Span::styled(seg.clone(), Style::default().fg(palette::FG)),
            ]));
        } else {
            out.push(Line::from(vec![
                Span::raw("  "),
                Span::styled(seg.clone(), Style::default().fg(palette::FG)),
            ]));
        }
    }
    out.push(Line::from(""));
    out
}

fn wrap_text(text: &str, max_width: usize) -> Vec<String> {
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
