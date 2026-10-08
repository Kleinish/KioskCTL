use anyhow::{Context, Result, bail};
use serde_json::{Value, json};
use std::{fs, path::Path, process::Stdio};
use tokio::process::Command;

fn has(program: &str) -> bool {
    std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).any(|d| d.join(program).is_file()))
        .unwrap_or(false)
}
async fn uid(user: &str) -> Option<String> {
    let o = Command::new("getent")
        .args(["passwd", user])
        .output()
        .await
        .ok()?;
    let line = String::from_utf8_lossy(&o.stdout);
    line.split(':').nth(2).map(str::to_owned)
}
pub async fn runtime_dir(c: &Value) -> String {
    let user = c
        .pointer("/system/kiosk_user")
        .and_then(Value::as_str)
        .unwrap_or("kioskctl");
    let mut candidates = Vec::new();
    let configured = c
        .pointer("/system/runtime_dir")
        .and_then(Value::as_str)
        .unwrap_or("auto");
    if configured != "auto" {
        candidates.push(configured.to_owned())
    }
    if let Some(id) = uid(user).await {
        candidates.push(format!("/run/user/{id}"))
    }
    candidates.extend(["/run/kioskctl-user".into(), "/run/kioskctl".into()]);
    // A D-Bus socket alone does not prove this is the Cage session.  Fedora
    // may create /run/user/<uid>/bus for the service account even though Cage
    // owns its Wayland socket in /run/kioskctl-user.  Prefer a live Wayland
    // socket so control commands target the actual kiosk compositor.
    candidates
        .iter()
        .find(|d| {
            fs::read_dir(d)
                .ok()
                .map(|r| {
                    r.flatten().any(|e| {
                        e.file_name().to_string_lossy().starts_with("wayland-")
                            && !e.file_name().to_string_lossy().ends_with(".lock")
                    })
                })
                .unwrap_or(false)
        })
        .cloned()
        .or_else(|| {
            candidates
                .into_iter()
                .find(|d| Path::new(d).join("bus").exists())
        })
        .unwrap_or_else(|| "/run/kioskctl-user".into())
}
fn display(c: &Value, dir: &str) -> String {
    let configured = c
        .pointer("/system/wayland_display")
        .and_then(Value::as_str)
        .unwrap_or("auto");
    if configured != "auto" {
        return configured.into();
    }
    fs::read_dir(dir)
        .ok()
        .and_then(|r| {
            r.flatten()
                .map(|e| e.file_name().to_string_lossy().into_owned())
                .filter(|n| n.starts_with("wayland-") && !n.ends_with(".lock"))
                .next()
        })
        .unwrap_or_else(|| "wayland-0".into())
}
async fn user_command(c: &Value, program: &str, args: &[String]) -> Result<String> {
    if !has("runuser") {
        bail!("runuser is required for kiosk session controls")
    };
    let user = c
        .pointer("/system/kiosk_user")
        .and_then(Value::as_str)
        .unwrap_or("kioskctl");
    let dir = runtime_dir(c).await;
    let wayland = display(c, &dir);
    let mut cmd = Command::new("runuser");
    cmd.args(["-u", user, "--", "env"])
        .arg(format!("XDG_RUNTIME_DIR={dir}"))
        .arg(format!("WAYLAND_DISPLAY={wayland}"));
    if Path::new(&dir).join("bus").exists() {
        cmd.arg(format!("DBUS_SESSION_BUS_ADDRESS=unix:path={dir}/bus"));
    }
    cmd.arg(program).args(args).stdin(Stdio::null());
    let out = cmd
        .output()
        .await
        .with_context(|| format!("run {program} as {user}"))?;
    if !out.status.success() {
        bail!(
            "{program} failed: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        )
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().into())
}

fn first_percent(out: &str) -> Option<i64> {
    out.split_whitespace().find_map(|x| {
        x.trim_matches(|c: char| c == '[' || c == ']' || c == ',')
            .strip_suffix('%')?
            .parse::<f64>()
            .ok()
            .map(|v| v.round() as i64)
    })
}
fn pipewire_percent(out: &str) -> Option<i64> {
    out.split("Volume:")
        .nth(1)?
        .split_whitespace()
        .next()?
        .parse::<f64>()
        .ok()
        .map(|v| (v * 100.0).round() as i64)
}
pub async fn audio(c: &Value) -> Value {
    let wanted = c
        .pointer("/audio/provider")
        .and_then(Value::as_str)
        .unwrap_or("auto");
    if (wanted == "auto" || wanted == "pipewire") && has("wpctl") {
        if let Ok(out) = user_command(
            c,
            "wpctl",
            &["get-volume".into(), "@DEFAULT_AUDIO_SINK@".into()],
        )
        .await
        {
            if let Some(volume) = pipewire_percent(&out) {
                return json!({"provider":"pipewire","volume":volume,"available":true});
            }
        }
    }
    if (wanted == "auto" || wanted == "pulseaudio") && has("pactl") {
        if let Ok(out) = user_command(
            c,
            "pactl",
            &["get-sink-volume".into(), "@DEFAULT_SINK@".into()],
        )
        .await
        {
            if let Some(volume) = first_percent(&out) {
                return json!({"provider":"pulseaudio","volume":volume,"available":true});
            }
        }
    }
    if (wanted == "auto" || wanted == "alsa") && has("amixer") {
        if let Ok(out) = user_command(c, "amixer", &["sget".into(), "Master".into()]).await {
            if let Some(volume) = first_percent(&out) {
                return json!({"provider":"alsa","volume":volume,"available":true});
            }
        }
    }
    json!({"provider":Value::Null,"volume":Value::Null,"available":false})
}
pub async fn set_volume(c: &Value, percent: i64) -> Result<String> {
    let p = percent.clamp(0, 100);
    let state = audio(c).await;
    let provider = state
        .get("provider")
        .and_then(Value::as_str)
        .context("no supported audio provider is available")?;
    let (program, args) = match provider {
        "pipewire" => (
            "wpctl",
            vec![
                "set-volume".into(),
                "@DEFAULT_AUDIO_SINK@".into(),
                format!("{p}%"),
            ],
        ),
        "pulseaudio" => (
            "pactl",
            vec![
                "set-sink-volume".into(),
                "@DEFAULT_SINK@".into(),
                format!("{p}%"),
            ],
        ),
        "alsa" => (
            "amixer",
            vec!["sset".into(), "Master".into(), format!("{p}%")],
        ),
        _ => bail!("unsupported audio provider"),
    };
    user_command(c, program, &args).await?;
    Ok(provider.into())
}
pub async fn brightness() -> Option<i64> {
    if !has("brightnessctl") {
        return None;
    }
    let out = Command::new("brightnessctl")
        .arg("-m")
        .output()
        .await
        .ok()?;
    if !out.status.success() {
        return None;
    }
    String::from_utf8_lossy(&out.stdout)
        .split(',')
        .find_map(|x| x.trim().strip_suffix('%')?.parse().ok())
}
pub async fn set_brightness(percent: i64) -> Result<()> {
    if !has("brightnessctl") {
        bail!("brightnessctl is not installed or no backlight device is available")
    }
    let out = Command::new("brightnessctl")
        .args(["set", &format!("{}%", percent.clamp(1, 100))])
        .output()
        .await?;
    if !out.status.success() {
        bail!(
            "brightnessctl failed: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        )
    }
    Ok(())
}
async fn outputs(c: &Value) -> Result<Vec<String>> {
    if !has("wlr-randr") {
        bail!("wlr-randr is not installed")
    };
    let out = user_command(c, "wlr-randr", &[]).await?;
    let wanted = c
        .pointer("/display/output")
        .and_then(Value::as_str)
        .unwrap_or("auto");
    if wanted != "auto" {
        return Ok(vec![wanted.into()]);
    }
    let names = out
        .lines()
        .filter(|line| !line.is_empty() && !line.starts_with(char::is_whitespace))
        .filter_map(|line| line.split_whitespace().next())
        .map(str::to_owned)
        .collect::<Vec<_>>();
    if names.is_empty() {
        bail!("no Wayland outputs detected")
    }
    Ok(names)
}
pub async fn display_diagnostics(c: &Value) -> Value {
    let dir = runtime_dir(c).await;
    let wayland = display(c, &dir);
    match outputs(c).await {
        Ok(names) => {
            json!({"runtime_dir":dir,"wayland_display":wayland,"source":"wlr-randr","outputs":names.into_iter().map(|name|json!({"name":name})).collect::<Vec<_>>() })
        }
        Err(e) => {
            json!({"runtime_dir":dir,"wayland_display":wayland,"source":"unavailable","outputs":[],"error":e.to_string()})
        }
    }
}
pub async fn apply_display_config(c: &Value) -> Result<Vec<String>> {
    let transform = c
        .pointer("/display/transform")
        .and_then(Value::as_str)
        .unwrap_or("normal");
    if !["normal", "90", "180", "270"].contains(&transform) {
        bail!("display.transform must be normal, 90, 180, or 270")
    }
    let scale = c
        .pointer("/display/scale")
        .and_then(Value::as_f64)
        .unwrap_or(1.0);
    if !(0.5..=3.0).contains(&scale) {
        bail!("display.scale must be between 0.5 and 3.0")
    }
    let outputs = outputs(c).await?;
    for output in &outputs {
        user_command(
            c,
            "wlr-randr",
            &vec![
                "--output".into(),
                output.clone(),
                "--transform".into(),
                transform.into(),
                "--scale".into(),
                scale.to_string(),
            ],
        )
        .await?;
    }
    Ok(outputs)
}
pub async fn display_power(c: &Value, on: bool) -> Result<Vec<String>> {
    let outputs = outputs(c).await?;
    for output in &outputs {
        user_command(
            c,
            "wlr-randr",
            &vec![
                "--output".into(),
                output.clone(),
                if on { "--on".into() } else { "--off".into() },
            ],
        )
        .await?;
    }
    Ok(outputs)
}
