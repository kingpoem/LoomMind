use std::io::{self, Write};
use std::process::{Child, ChildStdin};
use std::sync::mpsc::{Receiver, TryRecvError};
use std::time::Duration;

use crossterm::event::{self, Event, KeyEventKind};

use crate::child::ChildEvent;
use crate::session::events::{handle_child_event, handle_key};
use crate::session::input::insert_str;
use crate::session::state::App;
use crate::term::Term;
use crate::view::render::draw_inline;

pub fn run_loop(
    term: &mut Term,
    mut child: Child,
    mut child_stdin: ChildStdin,
    rx: Receiver<ChildEvent>,
    model_label: String,
) -> io::Result<()> {
    let mut app = App::new(model_label);

    loop {
        loop {
            match rx.try_recv() {
                Ok(ev) => handle_child_event(term, &mut app, ev)?,
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => {
                    handle_child_event(term, &mut app, ChildEvent::ProcessExited)?;
                    break;
                }
            }
        }

        app.tick_spinner();
        term.draw(|f| draw_inline(f, &app))?;

        if app.quit {
            break;
        }

        if event::poll(Duration::from_millis(80))? {
            match event::read()? {
                Event::Key(key)
                    if matches!(key.kind, KeyEventKind::Press | KeyEventKind::Repeat) =>
                {
                    handle_key(term, &mut app, &mut child_stdin, key)?;
                }
                Event::Paste(text) => {
                    insert_str(&mut app, &text);
                    app.refresh_popup();
                }
                Event::Resize(_, _) => {
                    term.autoresize()?;
                }
                _ => {}
            }
        }
    }

    let _ = writeln!(child_stdin, "{{\"type\":\"shutdown\"}}");
    let _ = child_stdin.flush();
    drop(child_stdin);
    let _ = child.wait();
    Ok(())
}
