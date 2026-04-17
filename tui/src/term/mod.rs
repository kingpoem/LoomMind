use std::io::{self, stdout, Write};

use crossterm::execute;
use crossterm::terminal::{disable_raw_mode, enable_raw_mode};
use ratatui::backend::CrosstermBackend;
use ratatui::{Terminal, TerminalOptions, Viewport};

use crate::theme::constants::INLINE_VIEWPORT_HEIGHT;

pub type Term = Terminal<CrosstermBackend<std::io::Stdout>>;

pub fn init_terminal() -> io::Result<Term> {
    enable_raw_mode()?;
    execute!(stdout(), crossterm::event::EnableBracketedPaste)?;
    let backend = CrosstermBackend::new(stdout());
    Terminal::with_options(
        backend,
        TerminalOptions {
            viewport: Viewport::Inline(INLINE_VIEWPORT_HEIGHT),
        },
    )
}

pub fn restore_terminal(term: &mut Term) -> io::Result<()> {
    let _ = term.clear();
    let area = term.get_frame().area();
    let _ = execute!(
        stdout(),
        crossterm::cursor::MoveTo(0, area.y + area.height.saturating_sub(1)),
        crossterm::style::Print("\n"),
        crossterm::cursor::Show,
    );
    execute!(stdout(), crossterm::event::DisableBracketedPaste)?;
    disable_raw_mode()?;
    let _ = stdout().flush();
    Ok(())
}
