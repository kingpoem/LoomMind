use std::io;

use ratatui::layout::Rect;
use ratatui::prelude::*;
use ratatui::style::Modifier;
use ratatui::widgets::{Block, Borders, Widget};

use crate::term::Term;
use crate::theme::constants::{APP_TITLE, APP_VERSION};
use crate::theme::palette;
use crate::util::directory_line;
use crate::view::history::render_line;

pub fn insert_header(term: &mut Term) -> io::Result<()> {
    let width = term.size()?.width.max(20);
    let dir = directory_line();

    // 边框包住的两行内容（backend / directory）。
    let info_lines: Vec<Line<'static>> = vec![
        Line::from(vec![
            Span::styled("backend:   ", Style::default().fg(palette::DIM)),
            Span::styled("python --cli --stdio", Style::default().fg(palette::FG)),
        ]),
        Line::from(vec![
            Span::styled("directory: ", Style::default().fg(palette::DIM)),
            Span::styled(dir, Style::default().fg(palette::FG)),
        ]),
    ];

    let title_line = Line::from(vec![
        Span::styled(
            ">_ ",
            Style::default()
                .fg(palette::ACCENT)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled(
            format!("{APP_TITLE} ({APP_VERSION})"),
            Style::default()
                .fg(palette::ACCENT)
                .add_modifier(Modifier::BOLD),
        ),
    ]);

    let body_height = info_lines.len() as u16 + 2; // border top + body + border bottom
    let total = 1 /* title */ + 1 /* blank */ + body_height + 1 /* blank */;

    term.insert_before(total, |buf| {
        render_line(buf, 0, &title_line, width);
        // blank between title and frame
        render_line(buf, 1, &Line::from(""), width);

        let area = Rect::new(0, 2, width, body_height);
        let block = Block::default()
            .borders(Borders::ALL)
            .border_style(Style::default().fg(palette::BORDER));
        let inner = block.inner(area);
        block.render(area, buf);

        for (i, l) in info_lines.iter().enumerate() {
            let _ = buf.set_line(inner.x, inner.y + i as u16, l, inner.width);
        }
        // trailing blank
        render_line(buf, total - 1, &Line::from(""), width);
    })
}
