use std::time::Duration;

pub const APP_TITLE: &str = "LoomMind";
pub const APP_VERSION: &str = "v0.1.0";

pub const COMPOSER_HEIGHT: u16 = 3;
pub const STATUS_HEIGHT: u16 = 1;

/// 弹层内容最大可见行数（不含上下边框）。
pub const POPUP_MAX_ROWS: u16 = 6;
/// 弹层占用的总高度：内容 + 上下边框。
pub const POPUP_AREA_HEIGHT: u16 = POPUP_MAX_ROWS + 2;

pub const INLINE_VIEWPORT_HEIGHT: u16 = COMPOSER_HEIGHT + POPUP_AREA_HEIGHT + STATUS_HEIGHT;

pub const SPINNER_FRAMES: &[&str] = &["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
pub const SPINNER_INTERVAL: Duration = Duration::from_millis(80);
