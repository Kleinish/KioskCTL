use anyhow::{Context, Result};
use axum::{
    Json, Router,
    extract::{Path as AxPath, Request, State},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use clap::{Parser, Subcommand};
use kioskctl::{VERSION, browser, config, hardware, plugin, state::AppState, system};
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::Arc,
};
use subtle::ConstantTimeEq;
use tower_http::{services::ServeDir, trace::TraceLayer};

#[derive(Parser)]
#[command(version, about)]
struct Cli {
    #[arg(
        long,
        env = "KIOSKCTL_CONFIG",
        default_value = "/etc/kioskctl/config.yaml"
    )]
    config: PathBuf,
    #[command(subcommand)]
    command: Option<Cmd>,
}
#[derive(Subcommand)]
enum Cmd {
    Serve,
    CheckConfig,
    PrintConfig,
    Doctor,
    RestartKiosk,
    Enable,
    Disable,
    BrowserSession,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();
    let cli = Cli::parse();
    let cfg = config::load(&cli.config)?;
    match cli.command.unwrap_or(Cmd::Serve) {
        Cmd::Serve => serve(cfg, cli.config).await,
        Cmd::CheckConfig => {
            println!("configuration is valid (schema {})", config::CONFIG_VERSION);
            Ok(())
        }
        Cmd::PrintConfig => {
            println!("{}", serde_yaml::to_string(&config::redacted(&cfg))?);
            Ok(())
        }
        Cmd::Doctor => {
            println!(
                "{}",
                serde_json::to_string_pretty(&diagnostics(&cfg).await)?
            );
            Ok(())
        }
        Cmd::RestartKiosk => {
            system::command("systemctl", &["restart", "kioskctl-browser.service"]).await?;
            Ok(())
        }
        Cmd::Enable => {
            let marker = system::enabled_marker(&cfg);
            if let Some(p) = Path::new(&marker).parent() {
                fs::create_dir_all(p)?
            }
            fs::write(marker, b"enabled\n")?;
            Ok(())
        }
        Cmd::Disable => {
            let _ = fs::remove_file(system::enabled_marker(&cfg));
            Ok(())
        }
        Cmd::BrowserSession => browser_session(&cfg).await,
    }
}

async fn browser_session(c: &Value) -> Result<()> {
    browser::run(c).await
}

async fn serve(cfg: Value, path: PathBuf) -> Result<()> {
    let host = cfg
        .pointer("/admin/host")
        .and_then(Value::as_str)
        .unwrap_or("0.0.0.0");
    let port = cfg
        .pointer("/admin/port")
        .and_then(Value::as_u64)
        .unwrap_or(2324);
    let bind = format!("{host}:{port}");
    let state = AppState::new(cfg, path);
    let plugin_dir = state
        .config
        .read()
        .await
        .pointer("/plugins/directory")
        .and_then(Value::as_str)
        .unwrap_or("/etc/kioskctl/plugins.d")
        .to_owned();
    if let Err(e) = state.plugins.discover(Path::new(&plugin_dir)).await {
        tracing::warn!("plugin discovery: {e:#}")
    }
    let app = Router::new()
        .route("/", get(index))
        .route("/api/health", get(health))
        .route("/api/status", get(status))
        .route("/api/screenshot", get(screenshot))
        .route("/api/browser/url", post(browser_url))
        .route("/api/browser/navigate", post(browser_navigate))
        .route("/api/browser/reload", post(browser_reload))
        .route("/api/browser/back", post(browser_back))
        .route("/api/input/click", post(input_click))
        .route("/api/input/text", post(input_text))
        .route("/api/input/key", post(input_key))
        .route("/api/display/on", post(display_on))
        .route("/api/display/off", post(display_off))
        .route("/api/display/brightness", post(set_brightness))
        .route("/api/audio/volume", post(set_volume))
        .route("/api/system/reboot", post(reboot))
        .route("/api/system/shutdown", post(shutdown))
        .route("/api/kiosk/enable", post(kiosk_enable))
        .route("/api/kiosk/disable", post(kiosk_disable))
        .route("/api/diagnostics", get(diag))
        .route("/api/plugins", get(plugins))
        .route("/api/plugins/manifests", get(plugins))
        .route("/api/plugins/catalog", get(plugins))
        .route("/api/plugins/{id}/call", post(plugin_call))
        .route(
            "/api/{*path}",
            get(generic_get).post(generic_post).delete(generic_delete),
        )
        .nest_service(
            "/static",
            ServeDir::new("/opt/kioskctl/web").fallback(ServeDir::new("web")),
        )
        .layer(TraceLayer::new_for_http())
        .with_state(state);
    let listener = tokio::net::TcpListener::bind(&bind)
        .await
        .with_context(|| format!("bind {bind}"))?;
    tracing::info!("kioskctl {VERSION} listening on {bind}");
    axum::serve(listener, app).await?;
    Ok(())
}

async fn index() -> Response {
    let installed = Path::new("/opt/kioskctl/web/index.html");
    let local = Path::new("web/index.html");
    let p = if installed.exists() { installed } else { local };
    match tokio::fs::read(p).await {
        Ok(b) => (
            [
                (header::CONTENT_TYPE, "text/html; charset=utf-8"),
                (header::CACHE_CONTROL, "no-store"),
            ],
            b,
        )
            .into_response(),
        Err(e) => (StatusCode::NOT_FOUND, e.to_string()).into_response(),
    }
}
async fn health() -> Json<Value> {
    Json(json!({"ok":true,"version":VERSION}))
}
fn authorized(headers: &HeaderMap, cfg: &Value) -> bool {
    if !cfg
        .pointer("/admin/auth/enabled")
        .and_then(Value::as_bool)
        .unwrap_or(true)
    {
        return true;
    }
    let expected = cfg
        .pointer("/admin/auth/token")
        .and_then(Value::as_str)
        .unwrap_or("")
        .as_bytes();
    let given = headers
        .get("x-api-key")
        .and_then(|x| x.to_str().ok())
        .unwrap_or("")
        .as_bytes();
    expected.len() == given.len() && bool::from(expected.ct_eq(given))
}
fn deny() -> Response {
    (
        StatusCode::UNAUTHORIZED,
        Json(json!({"detail":"invalid API token"})),
    )
        .into_response()
}
fn bad(e: anyhow::Error) -> Response {
    (
        StatusCode::BAD_REQUEST,
        Json(json!({"detail":e.to_string()})),
    )
        .into_response()
}
async fn screenshot(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match browser::screenshot(&c).await {
        Ok(png) => (
            [
                (header::CONTENT_TYPE, "image/png"),
                (header::CACHE_CONTROL, "no-store"),
            ],
            png,
        )
            .into_response(),
        Err(e) => bad(e),
    }
}
async fn browser_url(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    let url = match body.get("url").and_then(Value::as_str) {
        Some(v) => v.to_owned(),
        None => {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({"detail":"url is required"})),
            )
                .into_response();
        }
    };
    let mut c = s.config.write().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    if !url.starts_with("http://") && !url.starts_with("https://") && !url.starts_with("file://") {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({"detail":"URL must begin with http://, https://, or file://"})),
        )
            .into_response();
    }
    c["browser"]["url"] = json!(url);
    if let Err(e) = config::save(&s.config_path, &c) {
        return bad(e);
    }
    let snapshot = c.clone();
    drop(c);
    let mode = if browser::available(&snapshot).await {
        match browser::navigate(
            &snapshot,
            snapshot
                .pointer("/browser/url")
                .and_then(Value::as_str)
                .unwrap_or(""),
        )
        .await
        {
            Ok(_) => "navigated",
            Err(e) => return bad(e),
        }
    } else {
        match restart_browser().await {
            Ok(_) => "browser_started",
            Err(e) => return bad(e),
        }
    };
    Json(json!({"ok":true,"mode":mode})).into_response()
}
async fn browser_navigate(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match browser::navigate(&c, body.get("url").and_then(Value::as_str).unwrap_or("")).await {
        Ok(_) => Json(json!({"ok":true})).into_response(),
        Err(e) => bad(e),
    }
}
async fn browser_reload(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match browser::reload(&c).await {
        Ok(_) => Json(json!({"ok":true})).into_response(),
        Err(e) => bad(e),
    }
}
async fn browser_back(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match browser::back(&c).await {
        Ok(_) => Json(json!({"ok":true})).into_response(),
        Err(e) => bad(e),
    }
}
async fn input_click(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match browser::click(
        &c,
        body.get("x").and_then(Value::as_f64).unwrap_or(-1.0),
        body.get("y").and_then(Value::as_f64).unwrap_or(-1.0),
    )
    .await
    {
        Ok(_) => Json(json!({"ok":true})).into_response(),
        Err(e) => bad(e),
    }
}
async fn input_text(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match browser::text(&c, body.get("text").and_then(Value::as_str).unwrap_or("")).await {
        Ok(_) => Json(json!({"ok":true,"method":"CDP"})).into_response(),
        Err(e) => bad(e),
    }
}
async fn input_key(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match browser::key(&c, body.get("key").and_then(Value::as_str).unwrap_or("")).await {
        Ok(_) => Json(json!({"ok":true})).into_response(),
        Err(e) => bad(e),
    }
}
async fn display_on(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match hardware::display_power(&c, true).await {
        Ok(outputs) => Json(json!({"ok":true,"outputs":outputs})).into_response(),
        Err(e) => bad(e),
    }
}
async fn display_off(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match hardware::display_power(&c, false).await {
        Ok(_) => Json(json!({"ok":true})).into_response(),
        Err(e) => bad(e),
    }
}
async fn set_brightness(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match hardware::set_brightness(body.get("percent").and_then(Value::as_i64).unwrap_or(-1)).await
    {
        Ok(_) => Json(json!({"ok":true})).into_response(),
        Err(e) => bad(e),
    }
}
async fn set_volume(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    let p = body.get("percent").and_then(Value::as_i64).unwrap_or(-1);
    match hardware::set_volume(&c, p).await {
        Ok(provider) => {
            Json(json!({"ok":true,"percent":p.clamp(0,100),"provider":provider})).into_response()
        }
        Err(e) => bad(e),
    }
}
async fn kiosk_enable(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    let marker = system::enabled_marker(&c);
    if let Some(p) = Path::new(&marker).parent() {
        if let Err(e) = fs::create_dir_all(p) {
            return bad(e.into());
        }
    }
    if let Err(e) = fs::write(marker, b"enabled\n") {
        return bad(e.into());
    }
    drop(c);
    match restart_browser().await {
        Ok(_) => Json(json!({"ok":true})).into_response(),
        Err(e) => bad(e),
    }
}
async fn kiosk_disable(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    let _ = fs::remove_file(system::enabled_marker(&c));
    drop(c);
    let result = if which("systemctl") {
        system::command("systemctl", &["stop", "kioskctl-browser.service"]).await
    } else {
        system::command("rc-service", &["kioskctl-browser", "stop"]).await
    };
    match result {
        Ok(_) => Json(json!({"ok":true})).into_response(),
        Err(e) => bad(e),
    }
}
async fn restart_browser() -> Result<()> {
    if which("systemctl") {
        system::command(
            "systemctl",
            &["enable", "--now", "kioskctl-browser.service"],
        )
        .await?;
    } else {
        system::command("rc-update", &["add", "kioskctl-browser", "default"]).await?;
        system::command("rc-service", &["kioskctl-browser", "restart"]).await?;
    }
    Ok(())
}
async fn status(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    Json(status_payload(&c, s.started.elapsed().as_secs()).await).into_response()
}
// Keep the v0.5 web client usable while the Rust implementations of the
// browser/display providers are completed.  The UI consumes this flattened
// status document, whereas the on-disk YAML intentionally remains grouped by
// subsystem.  Never include secret values in this response.
async fn status_payload(c: &Value, agent_uptime: u64) -> Value {
    let metrics = system::metrics();
    let audio = hardware::audio(c).await;
    let brightness = hardware::brightness().await;
    let mqtt_password = c
        .pointer("/mqtt/password")
        .and_then(Value::as_str)
        .map(|v| !v.is_empty())
        .unwrap_or(false);
    let immich_key = c
        .pointer("/plugins/immich/api_key")
        .and_then(Value::as_str)
        .map(|v| !v.is_empty())
        .unwrap_or(false);
    let mut plugins = c.pointer("/plugins").cloned().unwrap_or_else(|| json!({}));
    if let Some(immich) = plugins.pointer_mut("/immich") {
        if let Some(o) = immich.as_object_mut() {
            o.remove("api_key");
            o.insert("api_key_set".into(), json!(immich_key));
        }
    }
    let distro = os_release();
    let configured_url = c.pointer("/browser/url").cloned().unwrap_or(json!(""));
    json!({
     "version":VERSION,"app":{"version":VERSION,"uptime_seconds":agent_uptime},
     "device_name":c.pointer("/device/name").cloned().unwrap_or(json!("kiosk")),"distro":distro,
     "cpu_percent":metrics["cpu_percent"],"memory_percent":metrics["memory_percent"],"disk_percent":metrics["disk_percent"],"uptime_seconds":metrics["uptime_seconds"],
     "temperature_c":Value::Null,"temperature_sensor":Value::Null,
     "kiosk_enabled":system::kiosk_enabled(c),"browser_active":browser::available(c).await,"browser_provider":c.pointer("/browser/provider").cloned().unwrap_or(json!("auto")),"browser_executable":browser::executable(c).map(Value::String).unwrap_or(json!("unavailable")),
     "configured_url":configured_url,"current_url":browser::current_url(c).await,"browser_experience":{"zoom":c.pointer("/browser/zoom").cloned().unwrap_or(json!(1.0)),"color_scheme":c.pointer("/browser/color_scheme").cloned().unwrap_or(json!("auto")),"pages":c.pointer("/browser/pages").cloned().unwrap_or(json!([])),"touch_ui":c.pointer("/browser/touch_ui").cloned().unwrap_or(json!({}))},
     "browser_prompts":c.pointer("/browser/prompts").cloned().unwrap_or(json!({})),"display_config":c.pointer("/display").cloned().unwrap_or(json!({})),"input_config":c.pointer("/input").cloned().unwrap_or(json!({})),"output_details":[],"input_devices":[],"wayland_display":Value::Null,
     "volume":audio["volume"],"audio_provider":audio["provider"],"audio":audio,"brightness":brightness,
     "monitoring":c.pointer("/monitoring").cloned().unwrap_or(json!({})),
     "idle":with_fields(c.pointer("/idle").cloned().unwrap_or(json!({})),json!({"state":"active","idle_seconds":0,"monitored_devices":[]})),
     "screensaver":with_fields(c.pointer("/screensaver").cloned().unwrap_or(json!({})),json!({"active":false,"images":image_names(c.pointer("/screensaver/image_dir").and_then(Value::as_str).unwrap_or("/var/lib/kioskctl/screensaver"))})),
     "mqtt":with_fields(c.pointer("/mqtt").cloned().unwrap_or(json!({})),json!({"connected":false,"password_set":mqtt_password,"client_id":Value::Null,"device_topic":Value::Null})),"plugins":plugins,"plugin_manifests":{},"touch_mapping":{"enabled":false,"touchscreens":[],"active_matrices":{}},"touch_pointer_suppression":{"enabled":false,"candidates":[]},"touchpad_suppression":{"enabled":false,"candidates":[]}
    })
}
fn with_fields(mut base: Value, extra: Value) -> Value {
    merge_object(&mut base, extra);
    base
}
fn os_release() -> Value {
    let text = fs::read_to_string("/etc/os-release").unwrap_or_default();
    let mut name = "Linux";
    let mut version = "";
    for line in text.lines() {
        if let Some(v) = line.strip_prefix("PRETTY_NAME=") {
            name = v.trim_matches('\"')
        } else if let Some(v) = line.strip_prefix("VERSION_ID=") {
            version = v.trim_matches('\"')
        }
    }
    json!({"name":name,"version":version})
}
async fn diag(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    Json(diagnostics(&c).await).into_response()
}
async fn diagnostics(c: &Value) -> Value {
    let audio = hardware::audio(c).await;
    let display = hardware::display_diagnostics(c).await;
    let browser_ready = browser::available(c).await;
    let runtime = display
        .get("runtime_dir")
        .and_then(Value::as_str)
        .unwrap_or("");
    let outputs = display
        .get("outputs")
        .and_then(Value::as_array)
        .map(|v| !v.is_empty())
        .unwrap_or(false);
    let checks = vec![
        json!({"id":"kiosk-user","ok":true,"message":format!("dedicated user {}",c.pointer("/system/kiosk_user").and_then(Value::as_str).unwrap_or("kioskctl"))}),
        json!({"id":"runtime-dir","ok":Path::new(runtime).exists(),"message":runtime}),
        json!({"id":"browser-executable","ok":browser::executable(c).is_some(),"message":browser::executable(c).unwrap_or_else(||"unavailable".into())}),
        json!({"id":"devtools","ok":browser_ready,"message":format!("127.0.0.1:{}",c.pointer("/browser/devtools_port").and_then(Value::as_u64).unwrap_or(9222))}),
        json!({"id":"wayland-output","ok":outputs,"message":display.get("error").and_then(Value::as_str).unwrap_or("output detected")}),
        json!({"id":"audio","ok":audio["available"],"message":audio["provider"].as_str().unwrap_or("no provider")}),
    ];
    let ok = checks
        .iter()
        .filter(|x| x.get("ok").and_then(Value::as_bool) == Some(true))
        .count();
    json!({"checks":checks,"summary":{"ok":ok,"warnings":checks.len()-ok},"browser":{"provider":c.pointer("/browser/provider").cloned().unwrap_or(json!("auto")),"version":Value::Null},"audio":audio,"display":display,"input_devices":[],"touch_mapping":{"enabled":false},"mqtt":{"enabled":c.pointer("/mqtt/enabled").and_then(Value::as_bool).unwrap_or(false),"connected":false,"host":c.pointer("/mqtt/host"),"port":c.pointer("/mqtt/port")},"plugins":{"homeassistant":c.pointer("/plugins/homeassistant").cloned().unwrap_or(json!({}))}})
}
async fn reboot(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match system::power(
        "reboot",
        c.pointer("/system/allow_power_actions")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    )
    .await
    {
        Ok(_) => Json(json!({"ok":true})).into_response(),
        Err(e) => bad(e),
    }
}
async fn shutdown(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match system::power(
        "shutdown",
        c.pointer("/system/allow_power_actions")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    )
    .await
    {
        Ok(_) => Json(json!({"ok":true})).into_response(),
        Err(e) => bad(e),
    }
}
fn which(n: &str) -> bool {
    std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).any(|d| d.join(n).exists()))
        .unwrap_or(false)
}
async fn plugins(State(s): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    let mut all = plugin::builtin_manifests();
    all.extend(s.plugins.list().await);
    Json(json!({"plugins":all})).into_response()
}
async fn plugin_call(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    AxPath(id): AxPath<String>,
    Json(body): Json<Value>,
) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    let allowed = c
        .pointer(&format!("/plugins/{id}/granted_permissions"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter_map(|v| v.as_str().map(str::to_owned))
        .collect();
    drop(c);
    match s
        .plugins
        .call(
            &id,
            body.get("method")
                .and_then(Value::as_str)
                .unwrap_or("status"),
            body.get("params").cloned().unwrap_or(json!({})),
            &allowed,
        )
        .await
    {
        Ok(v) => Json(v).into_response(),
        Err(e) => (
            StatusCode::BAD_GATEWAY,
            Json(json!({"detail":e.to_string()})),
        )
            .into_response(),
    }
}
async fn generic_get(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    AxPath(path): AxPath<String>,
) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    match path.as_str(){"mqtt/status"=>Json(json!({"enabled":c.pointer("/mqtt/enabled").and_then(Value::as_bool).unwrap_or(false),"connected":false,"host":c.pointer("/mqtt/host"),"port":c.pointer("/mqtt/port")})).into_response(),"idle/status"=>Json(json!({"enabled":c.pointer("/idle/enabled"),"state":"active"})).into_response(),"screensaver/images"=>Json(json!({"images":image_names(c.pointer("/screensaver/image_dir").and_then(Value::as_str).unwrap_or("/var/lib/kioskctl/screensaver"))})).into_response(),_=>Json(json!({"ok":true,"path":path})).into_response()}
}
async fn generic_post(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    AxPath(path): AxPath<String>,
    request: Request,
) -> Response {
    let mut c = s.config.write().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    let bytes = match axum::body::to_bytes(request.into_body(), 16 * 1024 * 1024).await {
        Ok(v) => v,
        Err(e) => return (StatusCode::BAD_REQUEST, e.to_string()).into_response(),
    };
    let body: Value = serde_json::from_slice(&bytes).unwrap_or_else(|_| json!({}));
    let pointer = match path.as_str() {
        "mqtt/config" => Some("/mqtt"),
        "idle/config" => Some("/idle"),
        "screensaver/config" => Some("/screensaver"),
        "display/config" => Some("/display"),
        "input/config" => Some("/input"),
        "monitoring/config" => Some("/monitoring/thresholds"),
        "plugins/homeassistant/config" => Some("/plugins/homeassistant"),
        "plugins/digital_signage/config" => Some("/plugins/digital_signage"),
        "plugins/immich/config" => Some("/plugins/immich"),
        _ => None,
    };
    if let Some(p) = pointer {
        if let Some(target) = c.pointer_mut(p) {
            merge_object(target, body)
        }
        if let Err(e) = config::save(&s.config_path, &c) {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({"detail":e.to_string()})),
            )
                .into_response();
        }
    }
    let snapshot = c.clone();
    drop(c);
    if path == "display/config" {
        return match hardware::apply_display_config(&snapshot).await {
            Ok(outputs) => Json(json!({"ok":true,"path":path,"applied":true,"outputs":outputs}))
                .into_response(),
            Err(e) => bad(e),
        };
    }
    Json(json!({"ok":true,"path":path})).into_response()
}
async fn generic_delete(
    State(s): State<Arc<AppState>>,
    headers: HeaderMap,
    AxPath(path): AxPath<String>,
) -> Response {
    let c = s.config.read().await;
    if !authorized(&headers, &c) {
        return deny();
    }
    Json(json!({"ok":true,"path":path})).into_response()
}
fn merge_object(target: &mut Value, patch: Value) {
    if let (Value::Object(a), Value::Object(b)) = (target, patch) {
        for (k, v) in b {
            if k.ends_with("password") || k.ends_with("api_key") {
                if v.as_str() == Some("") {
                    continue;
                }
            }
            a.insert(k, v);
        }
    }
}
fn image_names(dir: &str) -> Vec<String> {
    fs::read_dir(dir)
        .ok()
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| {
            let p = e.path();
            let ext = p.extension()?.to_str()?.to_ascii_lowercase();
            if ["jpg", "jpeg", "png", "webp", "gif", "avif", "bmp"].contains(&ext.as_str()) {
                e.file_name().into_string().ok()
            } else {
                None
            }
        })
        .collect()
}
