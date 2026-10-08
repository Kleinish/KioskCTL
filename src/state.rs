use serde_json::Value;
use std::{path::PathBuf, sync::Arc, time::Instant};
use tokio::sync::RwLock;
use crate::plugin::PluginRegistry;

pub struct AppState { pub config: RwLock<Value>, pub config_path: PathBuf, pub started: Instant, pub plugins: PluginRegistry }
impl AppState { pub fn new(config:Value,path:PathBuf)->Arc<Self>{Arc::new(Self{config:RwLock::new(config),config_path:path,started:Instant::now(),plugins:PluginRegistry::default()})} }
