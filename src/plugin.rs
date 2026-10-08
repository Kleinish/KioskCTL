use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{HashMap, HashSet},
    path::{Path, PathBuf},
    process::Stdio,
    time::Duration,
};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    process::Command,
    sync::RwLock,
    time::timeout,
};

pub const PROTOCOL_VERSION: u32 = 1;
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manifest {
    pub id: String,
    pub name: String,
    pub version: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub executable: String,
    #[serde(default)]
    pub capabilities: Vec<String>,
    #[serde(default)]
    pub permissions: Vec<String>,
    #[serde(default)]
    pub config_schema: Vec<Value>,
}
impl Manifest {
    pub fn validate(&self) -> Result<()> {
        if self.id.is_empty()
            || !self
                .id
                .chars()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-' || c == '_')
        {
            bail!("plugin id must match [a-z0-9_-]+")
        };
        if self.executable.is_empty() {
            bail!("plugin executable is required")
        };
        Ok(())
    }
}

#[derive(Default)]
pub struct PluginRegistry {
    manifests: RwLock<HashMap<String, Manifest>>,
    roots: RwLock<HashMap<String, PathBuf>>,
}
impl PluginRegistry {
    pub async fn discover(&self, dir: &Path) -> Result<usize> {
        let mut found = 0;
        if !dir.exists() {
            return Ok(0);
        };
        let mut rd = tokio::fs::read_dir(dir).await?;
        while let Some(ent) = rd.next_entry().await? {
            let p = ent.path();
            let manifest_path = if p.is_dir() {
                p.join("plugin.yaml")
            } else {
                continue;
            };
            if !manifest_path.exists() {
                continue;
            }
            let text = tokio::fs::read_to_string(&manifest_path).await?;
            let m: Manifest = serde_yaml::from_str(&text)
                .with_context(|| format!("parse {}", manifest_path.display()))?;
            m.validate()?;
            self.roots.write().await.insert(m.id.clone(), p);
            self.manifests.write().await.insert(m.id.clone(), m);
            found += 1;
        }
        Ok(found)
    }
    pub async fn list(&self) -> Vec<Manifest> {
        self.manifests.read().await.values().cloned().collect()
    }
    pub async fn call(
        &self,
        id: &str,
        method: &str,
        params: Value,
        allowed: &HashSet<String>,
    ) -> Result<Value> {
        let m = self
            .manifests
            .read()
            .await
            .get(id)
            .cloned()
            .context("plugin not found")?;
        for p in &m.permissions {
            if !allowed.contains(p) {
                bail!("plugin permission not granted: {p}")
            }
        }
        let root = self
            .roots
            .read()
            .await
            .get(id)
            .cloned()
            .context("plugin root missing")?;
        let exe = root.join(&m.executable);
        let mut child = Command::new(&exe)
            .current_dir(&root)
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("KIOSKCTL_PLUGIN_ID", id)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .with_context(|| format!("start {}", exe.display()))?;
        let req = json!({"jsonrpc":"2.0","id":1,"protocol":PROTOCOL_VERSION,"method":method,"params":params});
        let mut stdin = child.stdin.take().unwrap();
        stdin
            .write_all(serde_json::to_string(&req)?.as_bytes())
            .await?;
        stdin.write_all(b"\n").await?;
        drop(stdin);
        let mut line = String::new();
        let stdout = child.stdout.take().unwrap();
        let read = timeout(
            Duration::from_secs(10),
            BufReader::new(stdout).read_line(&mut line),
        )
        .await
        .context("plugin timed out")??;
        if read == 0 {
            bail!("plugin returned no response")
        };
        if line.len() > 1024 * 1024 {
            bail!("plugin response exceeds 1 MiB")
        };
        let response: Value =
            serde_json::from_str(&line).context("plugin returned invalid JSON")?;
        let status = timeout(Duration::from_secs(2), child.wait())
            .await
            .context("plugin did not exit")??;
        if !status.success() {
            bail!("plugin exited with {status}")
        };
        if let Some(e) = response.get("error") {
            bail!("plugin error: {e}")
        };
        Ok(response.get("result").cloned().unwrap_or(Value::Null))
    }
}

pub fn builtin_manifests() -> Vec<Manifest> {
    vec![
        Manifest {
            id: "homeassistant".into(),
            name: "Home Assistant".into(),
            version: "1.0".into(),
            description: "MQTT discovery and controls".into(),
            executable: "builtin".into(),
            capabilities: vec!["homeassistant.discovery".into(), "mqtt.entities".into()],
            permissions: vec![
                "mqtt.publish".into(),
                "mqtt.subscribe".into(),
                "status.read".into(),
            ],
            config_schema: vec![],
        },
        Manifest {
            id: "digital_signage".into(),
            name: "Digital Signage".into(),
            version: "1.0".into(),
            description: "Local scheduled signage slideshow".into(),
            executable: "builtin".into(),
            capabilities: vec!["screensaver.provider".into()],
            permissions: vec!["browser.navigate".into(), "filesystem.plugin-data".into()],
            config_schema: vec![],
        },
        Manifest {
            id: "immich".into(),
            name: "Immich Screensaver".into(),
            version: "1.1".into(),
            description: "Immich photo screensaver with original-source fitting".into(),
            executable: "builtin".into(),
            capabilities: vec![
                "screensaver.provider".into(),
                "immich.random".into(),
                "immich.album".into(),
            ],
            permissions: vec![
                "network.http".into(),
                "browser.navigate".into(),
                "secret.store".into(),
            ],
            config_schema: vec![],
        },
    ]
}
