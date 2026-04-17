use std::io;

mod child;
mod session;
mod term;
mod theme;
mod util;
mod view;

use child::{locate_project_root, read_model_label, spawn_child};
use term::{init_terminal, restore_terminal};
use view::header::insert_header;

fn main() -> io::Result<()> {
    let mut term = init_terminal()?;
    let result = (|| -> io::Result<()> {
        insert_header(&mut term)?;
        let project_root = locate_project_root()?;
        let model_label = read_model_label(&project_root);
        let (child, child_stdin, rx) = spawn_child(&project_root)?;
        session::run::run_loop(&mut term, child, child_stdin, rx, model_label)
    })();
    restore_terminal(&mut term)?;
    result
}
