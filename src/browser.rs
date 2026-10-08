use anyhow::{Context, Result, bail};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use futures_util::{SinkExt, StreamExt};
use serde_json::{Value, json};
use std::{collections::HashMap, path::Path, process::Stdio, time::Duration};
use tokio::{process::Command, time::timeout};
use tokio_tungstenite::{connect_async, tungstenite::Message};

fn port(c: &Value) -> u64 {
    c.pointer("/browser/devtools_port")
        .and_then(Value::as_u64)
        .unwrap_or(9222)
}
fn base(c: &Value) -> String {
    format!("http://127.0.0.1:{}", port(c))
}
pub fn executable(c: &Value) -> Option<String> {
    let configured = c
        .pointer("/browser/executable")
        .and_then(Value::as_str)
        .unwrap_or("auto");
    if configured != "auto" && Path::new(configured).is_file() {
        return Some(configured.to_owned());
    }
    for p in [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
    ] {
        if Path::new(p).is_file() {
            return Some(p.to_owned());
        }
    }
    for n in [
        "chromium",
        "chromium-browser",
        "google-chrome-stable",
        "google-chrome",
    ] {
        if let Some(paths) = std::env::var_os("PATH") {
            for d in std::env::split_paths(&paths) {
                if d.join(n).is_file() {
                    return Some(d.join(n).display().to_string());
                }
            }
        }
    }
    None
}
pub async fn available(c: &Value) -> bool {
    reqwest::Client::new()
        .get(format!("{}/json/version", base(c)))
        .timeout(Duration::from_secs(2))
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}
async fn target(c: &Value) -> Result<Value> {
    let targets: reqwest::Response = reqwest::Client::new()
        .get(format!("{}/json/list", base(c)))
        .timeout(Duration::from_secs(3))
        .send()
        .await?
        .error_for_status()?;
    let all: Vec<Value> = targets.json().await?;
    let preferred = c
        .pointer("/browser/url")
        .and_then(Value::as_str)
        .unwrap_or("");
    let pages: Vec<Value> = all
        .into_iter()
        .filter(|x| x.get("type").and_then(Value::as_str) == Some("page"))
        .collect();
    let external = pages
        .iter()
        .find(|x| {
            x.get("url")
                .and_then(Value::as_str)
                .map(|u| {
                    u == preferred
                        || u.starts_with(&format!("{}/", preferred.trim_end_matches('/')))
                })
                .unwrap_or(false)
        })
        .or_else(|| {
            pages.iter().find(|x| {
                x.get("url")
                    .and_then(Value::as_str)
                    .map(|u| {
                        u.starts_with("http://")
                            || u.starts_with("https://")
                            || u.starts_with("file://")
                    })
                    .unwrap_or(false)
            })
        })
        .or_else(|| pages.first())
        .context("no Chromium page target available")?;
    Ok(external.clone())
}
async fn call(c: &Value, method: &str, params: Value) -> Result<Value> {
    let t = target(c).await?;
    let ws = t
        .get("webSocketDebuggerUrl")
        .and_then(Value::as_str)
        .context("Chromium target lacks debugger URL")?;
    let (socket, _response) = connect_async(ws)
        .await
        .context("connect to Chromium DevTools")?;
    let (mut sink, mut stream) = socket.split();
    sink.send(Message::Text(
        json!({"id":1,"method":method,"params":params})
            .to_string()
            .into(),
    ))
    .await?;
    while let Some(message) = timeout(Duration::from_secs(5), stream.next())
        .await
        .context("DevTools timed out")?
    {
        let text = message?.into_text()?;
        let response: Value = serde_json::from_str(&text)?;
        if response.get("id").and_then(Value::as_i64) == Some(1) {
            if let Some(error) = response.get("error") {
                bail!("DevTools: {error}")
            }
            return Ok(response.get("result").cloned().unwrap_or(Value::Null));
        }
    }
    bail!("DevTools connection closed")
}
pub async fn current_url(c: &Value) -> Option<String> {
    target(c)
        .await
        .ok()?
        .get("url")
        .and_then(Value::as_str)
        .map(str::to_owned)
}
pub async fn screenshot(c: &Value) -> Result<Vec<u8>> {
    call(c, "Page.enable", json!({})).await?;
    let r = call(
        c,
        "Page.captureScreenshot",
        json!({"format":"png","fromSurface":true}),
    )
    .await?;
    STANDARD
        .decode(
            r.get("data")
                .and_then(Value::as_str)
                .context("screenshot data missing")?,
        )
        .context("decode screenshot")
}
pub async fn navigate(c: &Value, url: &str) -> Result<()> {
    if !url.starts_with("http://") && !url.starts_with("https://") && !url.starts_with("file://") {
        bail!("URL must begin with http://, https://, or file://")
    }
    call(c, "Page.bringToFront", json!({})).await?;
    call(c, "Page.navigate", json!({"url":url})).await?;
    Ok(())
}
pub async fn reload(c: &Value) -> Result<()> {
    call(c, "Page.bringToFront", json!({})).await?;
    call(c, "Page.reload", json!({"ignoreCache":true})).await?;
    Ok(())
}
pub async fn back(c: &Value) -> Result<()> {
    call(c, "Page.bringToFront", json!({})).await?;
    call(
        c,
        "Runtime.evaluate",
        json!({"expression":"history.back()"}),
    )
    .await?;
    Ok(())
}
pub async fn click(c: &Value, x: f64, y: f64) -> Result<()> {
    let r = call(
        c,
        "Runtime.evaluate",
        json!({"expression":"({w:innerWidth,h:innerHeight})","returnByValue":true}),
    )
    .await?;
    let v = r.pointer("/result/value").cloned().unwrap_or(json!({}));
    let px = x.clamp(0.0, 1.0) * v.get("w").and_then(Value::as_f64).unwrap_or(1.0);
    let py = y.clamp(0.0, 1.0) * v.get("h").and_then(Value::as_f64).unwrap_or(1.0);
    call(
        c,
        "Input.dispatchMouseEvent",
        json!({"type":"mousePressed","x":px,"y":py,"button":"left","clickCount":1}),
    )
    .await?;
    call(
        c,
        "Input.dispatchMouseEvent",
        json!({"type":"mouseReleased","x":px,"y":py,"button":"left","clickCount":1}),
    )
    .await?;
    Ok(())
}
pub async fn text(c: &Value, text: &str) -> Result<()> {
    call(c, "Input.insertText", json!({"text":text})).await?;
    Ok(())
}
pub async fn key(c: &Value, key: &str) -> Result<()> {
    let (code, vk) = match key {
        "Enter" => ("Enter", 13),
        "Tab" => ("Tab", 9),
        "Escape" => ("Escape", 27),
        "Backspace" => ("Backspace", 8),
        _ => bail!("unsupported key"),
    };
    let mut down = json!({"type":"rawKeyDown","key":key,"code":code,"windowsVirtualKeyCode":vk,"nativeVirtualKeyCode":vk});
    if key == "Enter" {
        down["type"] = json!("keyDown");
        down["text"] = json!("\r");
        down["unmodifiedText"] = json!("\r");
    }
    if key == "Backspace" {
        down["commands"] = json!(["deleteBackward"]);
    }
    call(c, "Input.dispatchKeyEvent", down).await?;
    call(c,"Input.dispatchKeyEvent",json!({"type":"keyUp","key":key,"code":code,"windowsVirtualKeyCode":vk,"nativeVirtualKeyCode":vk})).await?;
    Ok(())
}
pub fn custom_launcher(c: &Value) -> Option<&str> {
    c.pointer("/launcher/command")
        .and_then(Value::as_str)
        .filter(|v| !v.is_empty())
}
pub async fn run(c: &Value) -> Result<()> {
    if !crate::system::kiosk_enabled(c) {
        bail!("kiosk mode is disabled")
    };
    if let Some(command) = custom_launcher(c) {
        return run_custom(c, command).await;
    }
    let exe = executable(c).context("no Chromium/Chrome executable found")?;
    let url = c
        .pointer("/browser/url")
        .and_then(Value::as_str)
        .unwrap_or("https://example.com");
    let profile = c
        .pointer("/browser/user_data_dir")
        .and_then(Value::as_str)
        .filter(|v| *v != "auto")
        .unwrap_or("/var/lib/kioskctl/chromium");
    let _ = tokio::fs::create_dir_all(profile).await;
    let status = Command::new(exe)
        .args([
            "--kiosk",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--ozone-platform=wayland",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            &format!("--remote-debugging-port={}", port(c)),
            &format!("--user-data-dir={profile}"),
            url,
        ])
        .stdin(Stdio::null())
        .status()
        .await?;
    if !status.success() {
        bail!("browser exited with {status}")
    }
    Ok(())
}
async fn run_custom(c: &Value, command: &str) -> Result<()> {
    let path = Path::new(command);
    if !path.is_file() {
        bail!("launcher.command does not exist: {}", path.display())
    }
    let args = c
        .pointer("/launcher/args")
        .and_then(Value::as_array)
        .context("launcher.args must be a list")?
        .iter()
        .map(|v| {
            v.as_str()
                .context("launcher.args entries must be strings")
                .map(str::to_owned)
        })
        .collect::<Result<Vec<_>>>()?;
    let mut process = Command::new(path);
    process.args(args).stdin(Stdio::null());
    if let Some(dir) = c
        .pointer("/launcher/working_directory")
        .and_then(Value::as_str)
        .filter(|v| !v.is_empty())
    {
        process.current_dir(dir);
    }
    if let Some(env) = c
        .pointer("/launcher/environment")
        .and_then(Value::as_object)
    {
        let vars = env
            .iter()
            .map(|(k, v)| {
                Ok((
                    k,
                    v.as_str()
                        .context("launcher.environment values must be strings")?,
                ))
            })
            .collect::<Result<HashMap<_, _>>>()?;
        process.envs(vars);
    }
    let status = process.status().await?;
    if !status.success() {
        bail!("custom launcher exited with {status}")
    }
    Ok(())
}
