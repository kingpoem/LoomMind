use crate::session::state::App;
use crate::util::normalize_inline_text;

pub fn insert_char(app: &mut App, c: char) {
    let cleaned = normalize_inline_text(&c.to_string());
    if cleaned.is_empty() {
        return;
    }
    for ch in cleaned.chars() {
        app.input.insert(app.cursor, ch);
        app.cursor += ch.len_utf8();
    }
}

pub fn insert_str(app: &mut App, s: &str) {
    for c in normalize_inline_text(s).chars() {
        if c == '\n' || c == '\r' {
            continue;
        }
        insert_char(app, c);
    }
}

pub fn backspace(app: &mut App) {
    if app.cursor == 0 {
        return;
    }
    let prev = app.input[..app.cursor]
        .char_indices()
        .next_back()
        .map(|(i, _)| i)
        .unwrap_or(0);
    app.input.replace_range(prev..app.cursor, "");
    app.cursor = prev;
}

pub fn delete_forward(app: &mut App) {
    if app.cursor >= app.input.len() {
        return;
    }
    let next = app.input[app.cursor..]
        .chars()
        .next()
        .map(|c| app.cursor + c.len_utf8())
        .unwrap_or(app.input.len());
    app.input.replace_range(app.cursor..next, "");
}

pub fn move_left(app: &mut App) {
    if app.cursor == 0 {
        return;
    }
    let prev = app.input[..app.cursor]
        .char_indices()
        .next_back()
        .map(|(i, _)| i)
        .unwrap_or(0);
    app.cursor = prev;
}

pub fn move_right(app: &mut App) {
    if app.cursor >= app.input.len() {
        return;
    }
    let next = app.input[app.cursor..]
        .chars()
        .next()
        .map(|c| app.cursor + c.len_utf8())
        .unwrap_or(app.input.len());
    app.cursor = next;
}
