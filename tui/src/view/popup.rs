use ratatui::layout::Rect;
use ratatui::prelude::*;
use ratatui::style::{Modifier, Style};
use ratatui::widgets::{Block, Borders};
use unicode_width::UnicodeWidthStr;

use crate::theme::constants::POPUP_MAX_ROWS;
use crate::theme::palette;

#[derive(Debug, Clone, Copy)]
pub struct SlashCommand {
    pub name: &'static str,
    pub description: &'static str,
}

/// 仅保留与 Python 后端真实对接的命令。
pub const COMMANDS: &[SlashCommand] = &[
    SlashCommand {
        name: "model",
        description: "选择对话使用的模型",
    },
    SlashCommand {
        name: "skills",
        description: "勾选需要启用的 skills",
    },
    SlashCommand {
        name: "mcp",
        description: "勾选需要启用的 MCP 工具",
    },
    SlashCommand {
        name: "exit",
        description: "结束会话（同 /quit）",
    },
    SlashCommand {
        name: "quit",
        description: "结束会话（同 /exit）",
    },
];

#[derive(Debug, Default)]
pub struct SlashPopup {
    pub selected: usize,
    pub scroll: usize,
}

impl SlashPopup {
    pub fn new() -> Self {
        Self::default()
    }

    /// 仅当输入以 `/` 开头时显示斜杠命令提示。
    pub fn is_active(input: &str) -> bool {
        input.starts_with('/')
    }

    fn filter_token(input: &str) -> &str {
        input
            .strip_prefix('/')
            .unwrap_or("")
            .split_whitespace()
            .next()
            .unwrap_or("")
    }

    pub fn filtered(input: &str) -> Vec<&'static SlashCommand> {
        let filter = Self::filter_token(input).to_lowercase();
        if filter.is_empty() {
            return COMMANDS.iter().collect();
        }
        let mut exact = Vec::new();
        let mut prefix = Vec::new();
        for cmd in COMMANDS.iter() {
            let name = cmd.name.to_lowercase();
            if name == filter {
                exact.push(cmd);
            } else if name.starts_with(&filter) {
                prefix.push(cmd);
            }
        }
        exact.extend(prefix);
        exact
    }

    pub fn clamp(&mut self, len: usize) {
        if len == 0 {
            self.selected = 0;
            self.scroll = 0;
            return;
        }
        if self.selected >= len {
            self.selected = len - 1;
        }
        let max_visible = POPUP_MAX_ROWS as usize;
        if self.selected < self.scroll {
            self.scroll = self.selected;
        } else if self.selected >= self.scroll + max_visible {
            self.scroll = self.selected + 1 - max_visible;
        }
        if self.scroll + max_visible > len {
            self.scroll = len.saturating_sub(max_visible);
        }
    }

    pub fn move_up(&mut self, len: usize) {
        if len == 0 {
            return;
        }
        if self.selected == 0 {
            self.selected = len - 1;
        } else {
            self.selected -= 1;
        }
        self.clamp(len);
    }

    pub fn move_down(&mut self, len: usize) {
        if len == 0 {
            return;
        }
        self.selected = (self.selected + 1) % len;
        self.clamp(len);
    }

    pub fn reset(&mut self) {
        self.selected = 0;
        self.scroll = 0;
    }

    pub fn selected_command<'a>(&self, items: &[&'a SlashCommand]) -> Option<&'a SlashCommand> {
        items.get(self.selected).copied()
    }
}

/// 选择器（model / skills / mcp 公用），由 ChildEvent 异步填充列表。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SelectorKind {
    Model,
    Skills,
    Mcp,
}

#[derive(Debug)]
pub struct ToolApproval {
    pub id: String,
    pub tool: String,
    pub args: String,
    pub permissions: Vec<String>,
    pub cursor: usize,
}

impl ToolApproval {
    pub fn new(
        id: impl Into<String>,
        tool: impl Into<String>,
        args: impl Into<String>,
        permissions: Vec<String>,
    ) -> Self {
        Self {
            id: id.into(),
            tool: tool.into(),
            args: args.into(),
            permissions,
            cursor: 0,
        }
    }

    pub fn move_left(&mut self) {
        self.cursor = 0;
    }

    pub fn move_right(&mut self) {
        self.cursor = 1;
    }

    pub fn toggle(&mut self) {
        self.cursor = if self.cursor == 0 { 1 } else { 0 };
    }

    pub fn approved(&self) -> bool {
        self.cursor == 0
    }
}

#[derive(Debug)]
pub struct Selector {
    pub kind: SelectorKind,
    pub title: String,
    pub items: Vec<String>,
    pub selected: std::collections::BTreeSet<String>,
    pub multi: bool,
    pub cursor: usize,
    pub scroll: usize,
    pub loading: bool,
}

impl Selector {
    pub fn new(kind: SelectorKind, title: impl Into<String>, multi: bool) -> Self {
        Self {
            kind,
            title: title.into(),
            items: Vec::new(),
            selected: std::collections::BTreeSet::new(),
            multi,
            cursor: 0,
            scroll: 0,
            loading: true,
        }
    }

    pub fn populate(&mut self, items: Vec<String>, selected: Vec<String>) {
        self.items = items;
        self.selected = selected.into_iter().collect();
        self.cursor = 0;
        self.scroll = 0;
        self.loading = false;
    }

    pub fn move_up(&mut self) {
        let len = self.items.len();
        if len == 0 {
            return;
        }
        self.cursor = if self.cursor == 0 {
            len - 1
        } else {
            self.cursor - 1
        };
        self.adjust_scroll();
    }

    pub fn move_down(&mut self) {
        let len = self.items.len();
        if len == 0 {
            return;
        }
        self.cursor = (self.cursor + 1) % len;
        self.adjust_scroll();
    }

    fn adjust_scroll(&mut self) {
        let max_visible = visible_rows();
        if self.cursor < self.scroll {
            self.scroll = self.cursor;
        } else if self.cursor >= self.scroll + max_visible {
            self.scroll = self.cursor + 1 - max_visible;
        }
    }

    /// 单选时把选中项设置为当前游标项。
    pub fn pick_single(&mut self) -> Option<String> {
        let item = self.items.get(self.cursor)?.clone();
        self.selected.clear();
        self.selected.insert(item.clone());
        Some(item)
    }

    /// 多选时切换当前游标项。
    pub fn toggle(&mut self) {
        if let Some(item) = self.items.get(self.cursor).cloned() {
            if !self.selected.remove(&item) {
                self.selected.insert(item);
            }
        }
    }

    pub fn collect_selected(&self) -> Vec<String> {
        self.selected.iter().cloned().collect()
    }
}

fn visible_rows() -> usize {
    POPUP_MAX_ROWS as usize
}

// --- rendering ---------------------------------------------------------------

fn fit_popup_rect(area: Rect, inner_width: usize, inner_height: usize) -> Rect {
    let max_inner_w = area.width.saturating_sub(2) as usize;
    let max_inner_h = area.height.saturating_sub(2) as usize;
    let fit_inner_w = inner_width.clamp(1, max_inner_w.max(1));
    let fit_inner_h = inner_height.clamp(1, max_inner_h.max(1));
    Rect::new(
        area.x,
        area.y,
        (fit_inner_w + 2) as u16,
        (fit_inner_h + 2) as u16,
    )
}

fn render_block(frame: &mut Frame, area: Rect, title: &str) -> Rect {
    let surface = Style::default()
        .bg(palette::USER_BAR_BG)
        .fg(palette::USER_BAR_FG);
    let block = Block::default()
        .style(surface)
        .borders(Borders::ALL)
        .border_style(surface.fg(palette::SURFACE_MUTED))
        .title(Span::styled(
            format!(" {title} "),
            surface.fg(palette::SURFACE_MUTED),
        ));
    let inner = block.inner(area);
    frame.render_widget(block, area);
    inner
}

pub fn render_slash_popup(frame: &mut Frame, area: Rect, input: &str, state: &SlashPopup) {
    if area.height < 2 || area.width < 4 {
        return;
    }
    let title = "命令";
    let base = Style::default()
        .bg(palette::USER_BAR_BG)
        .fg(palette::USER_BAR_FG);
    let muted = base.fg(palette::SURFACE_MUTED);
    let selected_style = base
        .bg(palette::SURFACE_SELECTED_BG)
        .add_modifier(Modifier::BOLD);

    let items = SlashPopup::filtered(input);
    let title_w = UnicodeWidthStr::width(format!(" {title} ").as_str());
    let desired_inner_h = if items.is_empty() {
        1
    } else {
        items.len().min(visible_rows())
    };
    let desired_inner_w = if items.is_empty() {
        title_w.max(UnicodeWidthStr::width("  无匹配命令"))
    } else {
        let max_name_w = items
            .iter()
            .map(|c| UnicodeWidthStr::width(c.name) + 1)
            .max()
            .unwrap_or(0);
        let name_col = max_name_w + 2;
        let max_desc_w = items
            .iter()
            .map(|cmd| UnicodeWidthStr::width(cmd.description))
            .max()
            .unwrap_or(0);
        title_w.max(2 + name_col + max_desc_w)
    };
    let popup = fit_popup_rect(area, desired_inner_w, desired_inner_h);
    let inner = render_block(frame, popup, title);
    if items.is_empty() {
        write_line(
            frame,
            inner.x,
            inner.y,
            inner.width,
            "  无匹配命令",
            muted.add_modifier(Modifier::ITALIC),
        );
        return;
    }

    let max_name_w = items
        .iter()
        .map(|c| UnicodeWidthStr::width(c.name) + 1)
        .max()
        .unwrap_or(0);
    let name_col = max_name_w + 2;

    let max_visible = inner.height as usize;
    let start = state.scroll.min(items.len().saturating_sub(1));
    let end = (start + max_visible).min(items.len());

    for (row_idx, idx) in (start..end).enumerate() {
        let cmd = items[idx];
        let selected = idx == state.selected;
        let name = format!("/{}", cmd.name);
        let pad = name_col.saturating_sub(UnicodeWidthStr::width(name.as_str()));
        let style = if selected { selected_style } else { base };
        let desc_style = if selected { selected_style } else { muted };
        let line = Line::from(vec![
            Span::styled("  ", style),
            Span::styled(name, style),
            Span::styled(" ".repeat(pad), style),
            Span::styled(cmd.description.to_string(), desc_style),
        ]);
        let y = inner.y + row_idx as u16;
        if y >= inner.y + inner.height {
            break;
        }
        crate::view::history::render_buffer_line(frame, y, &line, inner.width, inner.x);
    }
}

pub fn render_selector(frame: &mut Frame, area: Rect, sel: &Selector) {
    if area.height < 2 || area.width < 4 {
        return;
    }
    let title_w = UnicodeWidthStr::width(format!(" {} ", sel.title).as_str());
    let max_mark_w = 4usize;
    let max_item_w = sel
        .items
        .iter()
        .map(|item| UnicodeWidthStr::width(item.as_str()))
        .max()
        .unwrap_or(0);
    let list_line_w = 2 + max_mark_w + max_item_w;
    let desired_inner_w = if sel.loading {
        title_w.max(UnicodeWidthStr::width("  加载中…"))
    } else if sel.items.is_empty() {
        title_w.max(UnicodeWidthStr::width("  （空列表）"))
    } else {
        title_w.max(list_line_w)
    };
    let desired_inner_h = if sel.loading {
        1
    } else if sel.items.is_empty() {
        2
    } else {
        sel.items.len().min(visible_rows()) + 1
    };
    let popup = fit_popup_rect(area, desired_inner_w, desired_inner_h);
    let inner = render_block(frame, popup, &sel.title);
    let base = Style::default()
        .bg(palette::USER_BAR_BG)
        .fg(palette::USER_BAR_FG);
    let muted = base.fg(palette::SURFACE_MUTED);
    let selected_style = base
        .bg(palette::SURFACE_SELECTED_BG)
        .add_modifier(Modifier::BOLD);

    if sel.loading {
        write_line(
            frame,
            inner.x,
            inner.y,
            inner.width,
            "  加载中…",
            muted.add_modifier(Modifier::ITALIC),
        );
        return;
    }

    if sel.items.is_empty() {
        write_line(
            frame,
            inner.x,
            inner.y,
            inner.width,
            "  （空列表）",
            muted.add_modifier(Modifier::ITALIC),
        );
        let hint = "  Esc 关闭";
        if inner.height > 1 {
            write_line(frame, inner.x, inner.y + 1, inner.width, hint, muted);
        }
        return;
    }

    let max_visible = (inner.height as usize).saturating_sub(1).max(1);
    let start = sel.scroll.min(sel.items.len().saturating_sub(1));
    let end = (start + max_visible).min(sel.items.len());

    for (row_idx, idx) in (start..end).enumerate() {
        let item = &sel.items[idx];
        let on_cursor = idx == sel.cursor;
        let chosen = sel.selected.contains(item);

        let mark = if sel.multi {
            if chosen {
                "[x] "
            } else {
                "[ ] "
            }
        } else if chosen {
            " ●  "
        } else {
            " ○  "
        };

        let cursor_marker = if on_cursor { "› " } else { "  " };

        let line_style = if on_cursor {
            selected_style
        } else if chosen {
            base
        } else {
            muted
        };

        let line = Line::from(vec![
            Span::styled(cursor_marker, line_style),
            Span::styled(mark.to_string(), line_style),
            Span::styled(item.clone(), line_style),
        ]);
        let y = inner.y + row_idx as u16;
        if y >= inner.y + inner.height {
            break;
        }
        crate::view::history::render_buffer_line(frame, y, &line, inner.width, inner.x);
    }

    let hint = if sel.multi {
        "  ↑/↓/j/k 选择 · Space 切换 · Enter 确认 · Esc 取消"
    } else {
        "  ↑/↓/j/k 选择 · Space 选中 · Enter 确认 · Esc 取消"
    };
    let y = inner.y + inner.height.saturating_sub(1);
    write_line(frame, inner.x, y, inner.width, hint, muted);
}

pub fn render_tool_approval(frame: &mut Frame, area: Rect, approval: &ToolApproval) {
    if area.height < 2 || area.width < 4 {
        return;
    }
    let inner = render_block(frame, area, "工具权限确认");
    let base = Style::default()
        .bg(palette::USER_BAR_BG)
        .fg(palette::USER_BAR_FG);
    let muted = base.fg(palette::SURFACE_MUTED);
    let selected_style = base
        .bg(palette::SURFACE_SELECTED_BG)
        .add_modifier(Modifier::BOLD);

    let tool_line = format!("  工具: {}", approval.tool);
    let args_line = format!("  参数: {}", approval.args);
    let perms = if approval.permissions.is_empty() {
        "无附加权限".to_string()
    } else {
        approval.permissions.join(", ")
    };
    let perms_line = format!("  权限: {perms}");

    let rows = [tool_line, args_line, perms_line];
    let mut y = inner.y;
    for row in rows {
        if y >= inner.y + inner.height {
            break;
        }
        write_line(frame, inner.x, y, inner.width, &row, muted);
        y += 1;
    }

    if y < inner.y + inner.height {
        render_approval_actions(frame, inner, y, approval, base, selected_style);
        y += 1;
    }
    if y < inner.y + inner.height {
        write_line(
            frame,
            inner.x,
            y,
            inner.width,
            "  ←/→ 切换 · Enter 确认 · Esc 拒绝",
            muted,
        );
    }
}

fn render_approval_actions(
    frame: &mut Frame,
    area: Rect,
    y: u16,
    approval: &ToolApproval,
    base: Style,
    selected_style: Style,
) {
    let allow_style = if approval.approved() {
        selected_style
    } else {
        base
    };
    let deny_style = if approval.approved() {
        base
    } else {
        selected_style
    };
    let line = Line::from(vec![
        Span::styled("  [", base),
        Span::styled("允许", allow_style),
        Span::styled("]   [", base),
        Span::styled("拒绝", deny_style),
        Span::styled("]", base),
    ]);
    crate::view::history::render_buffer_line(frame, y, &line, area.width, area.x);
}

fn write_line(frame: &mut Frame, x: u16, y: u16, width: u16, text: &str, style: Style) {
    let line = Line::from(Span::styled(text.to_string(), style));
    crate::view::history::render_buffer_line(frame, y, &line, width, x);
}
