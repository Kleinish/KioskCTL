use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use std::{fs, process::Stdio};
use sysinfo::{Disks, System};
use tokio::process::Command;
pub fn metrics() -> Value {
    let mut s = System::new_all();
    s.refresh_all();
    let cpu = s.global_cpu_usage();
    let memory = if s.total_memory() > 0 {
        s.used_memory() as f64 * 100.0 / s.total_memory() as f64
    } else {
        0.0
    };
    let disks = Disks::new_with_refreshed_list();
    let disk = disks
        .iter()
        .next()
        .map(|d| 100.0 - (d.available_space() as f64 * 100.0 / d.total_space().max(1) as f64))
        .unwrap_or(0.0);
    json!({"cpu_percent":cpu,"memory_percent":memory,"disk_percent":disk,"uptime_seconds":System::uptime()})
}
pub async fn command(program: &str, args: &[&str]) -> Result<String> {
    let out = Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .output()
        .await
        .with_context(|| format!("run {program}"))?;
    if !out.status.success() {
        bail!(
            "{program} failed: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        )
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().into())
}
pub async fn power(action: &str, allowed: bool) -> Result<()> {
    if !allowed {
        bail!("power actions are disabled in configuration")
    }
    let (program, arg) = match action {
        "reboot" if std::path::Path::new("/run/systemd/system").exists() => ("systemctl", "reboot"),
        "shutdown" if std::path::Path::new("/run/systemd/system").exists() => {
            ("systemctl", "poweroff")
        }
        "reboot" => ("reboot", ""),
        "shutdown" => ("poweroff", ""),
        _ => bail!("unknown power action"),
    };
    let mut cmd = Command::new(program);
    if !arg.is_empty() {
        cmd.arg(arg);
    }
    cmd.stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .with_context(|| format!("start {action}"))?;
    Ok(())
}
pub fn enabled_marker(config: &Value) -> String {
    config
        .pointer("/system/enabled_marker")
        .and_then(Value::as_str)
        .unwrap_or("/etc/kioskctl/kiosk.enabled")
        .into()
}
pub fn kiosk_enabled(config: &Value) -> bool {
    fs::metadata(enabled_marker(config)).is_ok()
}
