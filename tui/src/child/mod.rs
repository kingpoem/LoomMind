use std::io::{self, BufRead, BufReader, ErrorKind, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;

#[derive(Debug, Clone)]
pub enum ChildEvent {
    Ready {
        message: String,
        model: Option<String>,
    },
    System(String),
    AssistantDelta(String),
    AssistantMessage(String),
    TokenUsage {
        used: u64,
        limit: u64,
    },
    Error(String),
    SessionEnd(String),
    ProcessExited,

    Models {
        items: Vec<String>,
        current: Option<String>,
    },
    Skills {
        items: Vec<String>,
        selected: Vec<String>,
    },
    Mcps {
        items: Vec<String>,
        selected: Vec<String>,
    },
    ModelSet(String),
    SkillsSet(Vec<String>),
    McpsSet(Vec<String>),
    ToolConfirmRequest {
        id: String,
        tool: String,
        args: String,
        permissions: Vec<String>,
        preview: Option<String>,
    },
    ToolInvoked {
        tool: String,
        args: String,
    },
    TrustRequest {
        workspace: String,
    },
}

pub fn locate_project_root() -> io::Result<PathBuf> {
    if let Ok(env) = std::env::var("LOOMMIND_ROOT") {
        let p = PathBuf::from(env);
        if p.join("src/main.py").is_file() {
            return Ok(p);
        }
    }
    let mut cur = std::env::current_dir()?;
    loop {
        if cur.join("src/main.py").is_file() {
            return Ok(cur);
        }
        if !cur.pop() {
            return Err(io::Error::new(
                ErrorKind::NotFound,
                "找不到 LoomMind 项目根（缺少 src/main.py）",
            ));
        }
    }
}

pub fn read_model_label(_root: &PathBuf) -> String {
    "loommind".to_string()
}

pub fn spawn_child(root: &PathBuf) -> io::Result<(Child, ChildStdin, Receiver<ChildEvent>)> {
    let log_path = std::env::temp_dir().join("loommind-tui-child.log");
    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)?;

    let mut child = Command::new("uv")
        .args(["run", "python", "src/main.py", "--cli", "--stdio"])
        .current_dir(root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::from(log_file))
        .spawn()?;

    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| io::Error::other("无法获取子进程 stdin"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| io::Error::other("无法获取子进程 stdout"))?;

    let (tx, rx) = mpsc::channel();
    spawn_reader_thread(stdout, tx.clone());

    Ok((child, stdin, rx))
}

/// 写一行 NDJSON 命令到子进程；忽略写错误的细节，由调用方决定如何处理。
pub fn send_command(stdin: &mut ChildStdin, value: serde_json::Value) -> io::Result<()> {
    writeln!(stdin, "{value}")?;
    stdin.flush()
}

fn spawn_reader_thread(stdout: std::process::ChildStdout, tx: Sender<ChildEvent>) {
    thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line_res in reader.lines() {
            let line = match line_res {
                Ok(l) => l,
                Err(_) => break,
            };
            if line.trim().is_empty() {
                continue;
            }
            let event = match parse_event(&line) {
                Ok(ev) => ev,
                Err(err) => ChildEvent::Error(format!("解析事件失败: {err} ({line})")),
            };
            if tx.send(event).is_err() {
                break;
            }
        }
        let _ = tx.send(ChildEvent::ProcessExited);
    });
}

fn parse_event(line: &str) -> Result<ChildEvent, String> {
    let value: serde_json::Value = serde_json::from_str(line).map_err(|e| e.to_string())?;
    let ty = value
        .get("type")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "缺少 type 字段".to_string())?;
    let s = |k: &str| -> String {
        value
            .get(k)
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    };
    let str_array = |k: &str| -> Vec<String> {
        value
            .get(k)
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default()
    };
    Ok(match ty {
        "ready" => {
            let model = value
                .get("model")
                .and_then(|v| v.as_str())
                .map(String::from);
            ChildEvent::Ready {
                message: s("message"),
                model,
            }
        }
        "system" => ChildEvent::System(s("message")),
        "assistant_delta" => ChildEvent::AssistantDelta(s("text")),
        "assistant_message" => ChildEvent::AssistantMessage(s("text")),
        "token_usage" => {
            let used = value.get("used").and_then(|v| v.as_u64()).unwrap_or(0);
            let limit = value.get("limit").and_then(|v| v.as_u64()).unwrap_or(0);
            ChildEvent::TokenUsage { used, limit }
        }
        "error" => ChildEvent::Error(s("message")),
        "session_end" => ChildEvent::SessionEnd(s("reason")),
        "models" => {
            let current = value
                .get("current")
                .and_then(|v| v.as_str())
                .map(String::from);
            ChildEvent::Models {
                items: str_array("items"),
                current,
            }
        }
        "skills" => ChildEvent::Skills {
            items: str_array("items"),
            selected: str_array("selected"),
        },
        "mcps" => ChildEvent::Mcps {
            items: str_array("items"),
            selected: str_array("selected"),
        },
        "model_set" => ChildEvent::ModelSet(s("name")),
        "skills_set" => ChildEvent::SkillsSet(str_array("selected")),
        "mcps_set" => ChildEvent::McpsSet(str_array("selected")),
        "tool_confirm_request" => {
            let args = value
                .get("args")
                .map(|v| serde_json::to_string(v).unwrap_or_else(|_| "{}".to_string()))
                .unwrap_or_else(|| "{}".to_string());
            let preview = value
                .get("preview")
                .and_then(|v| v.as_str())
                .map(String::from);
            ChildEvent::ToolConfirmRequest {
                id: s("id"),
                tool: s("tool"),
                args,
                permissions: str_array("permissions"),
                preview,
            }
        }
        "tool_invoked" => {
            let args = value
                .get("args")
                .map(|v| serde_json::to_string(v).unwrap_or_else(|_| "{}".to_string()))
                .unwrap_or_else(|| "{}".to_string());
            ChildEvent::ToolInvoked {
                tool: s("tool"),
                args,
            }
        }
        "trust_request" => ChildEvent::TrustRequest {
            workspace: s("workspace"),
        },
        other => ChildEvent::System(format!("未知事件 {other}: {line}")),
    })
}
