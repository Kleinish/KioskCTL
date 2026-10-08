use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use std::{
    fs,
    io::Write,
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
};

pub const CONFIG_VERSION: u64 = 12;

pub fn default_config() -> Value {
    json!({
      "version": CONFIG_VERSION, "device":{"name":"kiosk"},
      "browser":{"url":"https://example.com","provider":"auto","executable":"auto","user_data_dir":"auto","incognito":false,"devtools_port":9222,"extra_args":[],"pages":[],"zoom":1.0,"color_scheme":"auto","touch_ui":{"pull_to_refresh":true,"pull_threshold_px":110,"edge_drawer":false,"onscreen_keyboard":false},"prompts":{"password_manager":false,"notifications":"block","translate":false,"autofill":false}},
      "launcher":{"command":"","args":[],"working_directory":"","environment":{}},
      "admin":{"host":"0.0.0.0","port":2324,"auth":{"enabled":true,"token":"CHANGE_ME"}},
      "system":{"kiosk_user":"kioskctl","session_service":"getty@tty1.service","tty":"tty1","runtime_dir":"auto","wayland_display":"auto","allow_power_actions":true,"enabled_marker":"/etc/kioskctl/kiosk.enabled"},
      "display":{"output":"auto","mode":"preferred","refresh_hz":"auto","scale":1.0,"transform":"normal","settle_timeout":12.0,"settle_delay":1.0,"reinitialize_on_start":true,"brightness_backend":"auto"},
      "input":{"rotate_touch_with_display":true,"ignore_touch_mouse_emulation":true,"disable_touchpad_in_kiosk":false},
      "audio":{"provider":"auto"},"temperature":{"primary":"auto"},
      "monitoring":{"thresholds":{"cpu_percent":90,"memory_percent":90,"disk_percent":90,"temperature_c":80}},
      "idle":{"enabled":false,"dim_after_seconds":300,"off_after_seconds":600,"dim_brightness":20,"wake_on_input":true},
      "screensaver":{"enabled":false,"after_seconds":120,"interval_seconds":10,"fit":"contain","shuffle":false,"background":"#000000","keep_display_on":true,"image_dir":"/var/lib/kioskctl/screensaver"},
      "mqtt":{"enabled":false,"host":"127.0.0.1","port":1883,"username":"","password":"","base_topic":"kioskctl"},
      "plugins":{"directory":"/etc/kioskctl/plugins.d","homeassistant":{"enabled":false,"discovery_prefix":"homeassistant"},"digital_signage":{"installed":false,"enabled":false,"after_seconds":120,"interval_seconds":10,"fit":"cover","shuffle":false,"background":"#000000","keep_display_on":true,"schedule_enabled":false,"schedule_start":"00:00","schedule_end":"23:59","schedule_days":[0,1,2,3,4,5,6],"asset_dir":"/var/lib/kioskctl/plugins/digital-signage/assets"},"immich":{"installed":false,"enabled":false,"server_url":"","api_key":"","album_id":"","after_seconds":120,"interval_seconds":15,"fit":"contain","background":"#000000","keep_display_on":true,"random_count":100,"cache_seconds":300}},
      "update":{"command":""}
    })
}

fn merge(base: &mut Value, overlay: Value) {
    match (base, overlay) {
        (Value::Object(a), Value::Object(b)) => {
            for (k, v) in b {
                merge(a.entry(k).or_insert(Value::Null), v);
            }
        }
        (a, b) => *a = b,
    }
}

pub fn migrate(mut raw: Value) -> Result<Value> {
    let version = raw.get("version").and_then(Value::as_u64).unwrap_or(1);
    if version > CONFIG_VERSION {
        bail!("config version {version} is newer than supported version {CONFIG_VERSION}")
    }
    if version <= 3 {
        let mqtt = raw.get_mut("mqtt").and_then(Value::as_object_mut);
        let (enabled, prefix) = mqtt
            .map(|m| {
                (
                    m.remove("home_assistant_discovery"),
                    m.remove("discovery_prefix"),
                )
            })
            .unwrap_or((None, None));
        let root = raw
            .as_object_mut()
            .context("config root must be a mapping")?;
        let plugins = root
            .entry("plugins")
            .or_insert_with(|| json!({}))
            .as_object_mut()
            .context("plugins must be a mapping")?;
        let ha = plugins
            .entry("homeassistant")
            .or_insert_with(|| json!({}))
            .as_object_mut()
            .context("homeassistant must be a mapping")?;
        if let Some(v) = enabled {
            ha.insert("enabled".into(), v);
        }
        if let Some(v) = prefix {
            ha.insert("discovery_prefix".into(), v);
        }
    }
    raw["version"] = json!(CONFIG_VERSION);
    let mut out = default_config();
    merge(&mut out, raw);
    validate(&out)?;
    Ok(out)
}

pub fn validate(c: &Value) -> Result<()> {
    for (path, v) in [
        ("admin.port", c.pointer("/admin/port")),
        ("browser.devtools_port", c.pointer("/browser/devtools_port")),
        ("mqtt.port", c.pointer("/mqtt/port")),
    ] {
        let p = v
            .and_then(Value::as_u64)
            .with_context(|| format!("{path} must be an integer"))?;
        if !(1..=65535).contains(&p) {
            bail!("{path} must be between 1 and 65535")
        }
    }
    let zoom = c
        .pointer("/browser/zoom")
        .and_then(Value::as_f64)
        .unwrap_or(1.0);
    if !(0.5..=2.0).contains(&zoom) {
        bail!("browser.zoom must be between 0.5 and 2.0")
    }
    let fit = c
        .pointer("/screensaver/fit")
        .and_then(Value::as_str)
        .unwrap_or("contain");
    if !["contain", "cover"].contains(&fit) {
        bail!("screensaver.fit must be contain or cover")
    }
    let bg = c
        .pointer("/screensaver/background")
        .and_then(Value::as_str)
        .unwrap_or("");
    if bg.len() != 7 || !bg.starts_with('#') || !bg[1..].chars().all(|x| x.is_ascii_hexdigit()) {
        bail!("screensaver.background must be #RRGGBB")
    }
    let command = c
        .pointer("/launcher/command")
        .and_then(Value::as_str)
        .unwrap_or("");
    if !command.is_empty() && !Path::new(command).is_absolute() {
        bail!("launcher.command must be an absolute path, or empty to use Chromium")
    }
    if !c
        .pointer("/launcher/args")
        .map(Value::is_array)
        .unwrap_or(true)
    {
        bail!("launcher.args must be a list")
    }
    if !c
        .pointer("/launcher/environment")
        .map(Value::is_object)
        .unwrap_or(true)
    {
        bail!("launcher.environment must be a mapping")
    }
    Ok(())
}

pub fn load(path: &Path) -> Result<Value> {
    if !path.exists() {
        return Ok(default_config());
    };
    let text = fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    migrate(serde_yaml::from_str(&text).context("parse YAML")?)
}

pub fn save(path: &Path, c: &Value) -> Result<()> {
    let valid = migrate(c.clone())?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?
    };
    let tmp = PathBuf::from(format!("{}.tmp", path.display()));
    let previous = fs::metadata(path).ok();
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(&tmp)?;
    file.write_all(serde_yaml::to_string(&valid)?.as_bytes())?;
    file.sync_all()?;
    if let Some(meta) = previous {
        fs::set_permissions(&tmp, fs::Permissions::from_mode(meta.mode() & 0o777))?;
        unsafe {
            libc_chown(&tmp, meta.uid(), meta.gid())?;
        }
    }
    fs::rename(tmp, path)?;
    Ok(())
}

unsafe fn libc_chown(path: &Path, uid: u32, gid: u32) -> Result<()> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    let p = CString::new(path.as_os_str().as_bytes())?;
    if unsafe { libc::chown(p.as_ptr(), uid, gid) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
}

pub fn redacted(c: &Value) -> Value {
    let mut x = c.clone();
    for p in [
        "/admin/auth/token",
        "/mqtt/password",
        "/plugins/immich/api_key",
    ] {
        if let Some(v) = x.pointer_mut(p) {
            let set = v.as_str().map(|s| !s.is_empty()).unwrap_or(false);
            *v = json!(if set { "***" } else { "" });
        }
    }
    x
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn migrates_old() {
        let x = migrate(json!({"version":3,"mqtt":{"home_assistant_discovery":true}})).unwrap();
        assert_eq!(x["version"], 12);
        assert_eq!(
            x.pointer("/plugins/homeassistant/enabled"),
            Some(&json!(true))
        );
    }
    #[test]
    fn rejects_future() {
        assert!(migrate(json!({"version":99})).is_err());
    }
    #[test]
    fn rejects_relative_launcher() {
        assert!(migrate(json!({"launcher":{"command":"my-app"}})).is_err());
    }
}
