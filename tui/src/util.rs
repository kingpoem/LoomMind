use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

pub fn directory_line() -> String {
    let path = std::env::current_dir()
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_default();
    if let Some(home) = std::env::var_os("HOME") {
        let home = home.to_string_lossy().into_owned();
        if path.starts_with(&home) {
            return format!("~{}", &path[home.len()..]);
        }
    }
    path
}

pub fn truncate_to_width(s: &str, max: usize) -> String {
    if s.width() <= max {
        return s.to_string();
    }
    let mut acc = 0usize;
    let mut end = 0usize;
    for (i, ch) in s.char_indices() {
        let w = UnicodeWidthChar::width(ch).unwrap_or(0);
        if acc + w > max.saturating_sub(1) {
            break;
        }
        acc += w;
        end = i + ch.len_utf8();
    }
    format!("{}…", &s[..end])
}

pub fn truncate_left_to_width(s: &str, max: usize) -> String {
    if s.width() <= max {
        return s.to_string();
    }
    let mut acc = 0usize;
    let mut start_byte = s.len();
    for (i, ch) in s.char_indices().rev() {
        let w = UnicodeWidthChar::width(ch).unwrap_or(0);
        if acc + w > max.saturating_sub(1) {
            break;
        }
        acc += w;
        start_byte = i;
    }
    format!("…{}", &s[start_byte..])
}

/// Normalize odd spacing artifacts from IME / model stream output.
///
/// - drop zero-width/control separators that may render as tofu blocks
/// - normalize uncommon unicode spaces into ASCII space
/// - remove spaces between CJK/full-width characters
pub fn normalize_inline_text(s: &str) -> String {
    let normalized: Vec<char> = s
        .chars()
        .filter_map(|ch| {
            if is_ignored_spacing(ch) {
                None
            } else if is_unicode_space(ch) {
                Some(' ')
            } else {
                Some(ch)
            }
        })
        .collect();

    let mut out = String::with_capacity(normalized.len());
    for (idx, ch) in normalized.iter().copied().enumerate() {
        if ch == ' ' && idx > 0 && idx + 1 < normalized.len() {
            let prev = normalized[idx - 1];
            let next = normalized[idx + 1];
            if is_cjk_or_fullwidth(prev) && is_cjk_or_fullwidth(next) {
                continue;
            }
        }
        out.push(ch);
    }
    out
}

fn is_ignored_spacing(ch: char) -> bool {
    matches!(
        ch,
        '\u{200B}' // ZERO WIDTH SPACE
            | '\u{200C}' // ZERO WIDTH NON-JOINER
            | '\u{200D}' // ZERO WIDTH JOINER
            | '\u{2060}' // WORD JOINER
            | '\u{FEFF}' // ZERO WIDTH NO-BREAK SPACE / BOM
    )
}

fn is_unicode_space(ch: char) -> bool {
    matches!(
        ch,
        '\u{00A0}' // NO-BREAK SPACE
            | '\u{1680}'
            | '\u{2000}'
            | '\u{2001}'
            | '\u{2002}'
            | '\u{2003}'
            | '\u{2004}'
            | '\u{2005}'
            | '\u{2006}'
            | '\u{2007}'
            | '\u{2008}'
            | '\u{2009}'
            | '\u{200A}'
            | '\u{202F}'
            | '\u{205F}'
            | '\u{3000}' // IDEOGRAPHIC SPACE
    )
}

fn is_cjk_or_fullwidth(ch: char) -> bool {
    matches!(
        ch as u32,
        0x2E80..=0x2FFF // CJK radicals / symbols / punctuation
            | 0x3000..=0x303F // CJK symbols and punctuation
            | 0x3040..=0x30FF // Hiragana / Katakana
            | 0x3400..=0x4DBF // CJK Extension A
            | 0x4E00..=0x9FFF // CJK Unified Ideographs
            | 0xF900..=0xFAFF // CJK Compatibility Ideographs
            | 0xFF00..=0xFFEF // Full-width ASCII variants / punctuation
    )
}
