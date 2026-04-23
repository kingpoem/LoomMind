use std::time::Instant;

use crate::child::ModelConfigItem;
use crate::theme::constants;
use crate::view::popup::{
    Selector, SlashPopup, SubagentPermissionSelector, TextPrompt, ToolApproval, TrustApproval,
};

#[derive(Debug, PartialEq, Eq)]
pub enum SessionState {
    Idle,
    Working,
}

#[derive(Debug, Default)]
pub enum Overlay {
    #[default]
    None,
    Selector(Selector),
    TextPrompt(TextPrompt),
    Approval(ToolApproval),
    Trust(TrustApproval),
    SubagentPermission(SubagentPermissionSelector),
}

impl Overlay {
    pub fn is_active(&self) -> bool {
        !matches!(self, Overlay::None)
    }
}

pub struct App {
    pub input: String,
    pub cursor: usize,
    pub quit: bool,
    pub state: SessionState,
    pub assistant_buf: String,
    pub status: String,
    pub last_token_usage: Option<(u64, u64)>,
    pub spinner_idx: usize,
    pub spinner_last: Instant,
    pub model_label: String,
    pub llm_provider_label: String,
    /// 选模型后「多项配置」列表备份，用于从输入框 Esc 返回列表
    pub config_menu_backup: Option<Vec<ModelConfigItem>>,
    pub popup: SlashPopup,
    pub overlay: Overlay,
}

impl App {
    pub fn new(model_label: String) -> Self {
        Self {
            input: String::new(),
            cursor: 0,
            quit: false,
            state: SessionState::Idle,
            assistant_buf: String::new(),
            status: "启动中…".into(),
            last_token_usage: None,
            spinner_idx: 0,
            spinner_last: Instant::now(),
            model_label,
            llm_provider_label: "…".into(),
            config_menu_backup: None,
            popup: SlashPopup::new(),
            overlay: Overlay::None,
        }
    }

    pub fn tick_spinner(&mut self) {
        if self.state == SessionState::Working
            && self.spinner_last.elapsed() >= constants::SPINNER_INTERVAL
        {
            self.spinner_idx = (self.spinner_idx + 1) % constants::SPINNER_FRAMES.len();
            self.spinner_last = Instant::now();
        }
    }

    /// Recompute popup state after input changes.
    pub fn refresh_popup(&mut self) {
        if SlashPopup::is_active(&self.input) {
            let len = SlashPopup::filtered(&self.input).len();
            self.popup.clamp(len);
        } else {
            self.popup.reset();
        }
    }
}
