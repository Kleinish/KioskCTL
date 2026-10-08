from __future__ import annotations

import copy
import base64
import html
import re
from urllib.parse import quote
import logging
import os
import shlex
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .browser import DevTools, browser_provider, chromium_executable, resolved_user_data_dir, write_managed_policy
from .config import DEFAULT_PATH, load_config, save_config
from .diagnostics import diagnostic_report
from .mqtt import MQTTBridge
from .events import EventBus
from .idle import IdleManager
from .plugins import (DigitalSignagePlugin, HomeAssistantPlugin, ImmichPlugin, PluginManager)
from .platform import (WaylandTools, distro_info, input_devices, install_touch_transform,
                       install_touch_pointer_suppression, install_touchpad_suppression, power_action, system_metrics,
                       temperature_sensors, touch_mapping_status, touch_pointer_suppression_status,
                       touchpad_suppression_status)
from .session import disable as disable_kiosk_session
from .session import enable as enable_kiosk_session
from .session import enabled as kiosk_enabled
from .session import restart as restart_kiosk_session

APP_VERSION = "0.5.2"
CONFIG_PATH = Path(os.environ.get("KIOSKCTL_CONFIG", str(DEFAULT_PATH)))
cfg = load_config(CONFIG_PATH)
cfg_lock = threading.RLock()
logger = logging.getLogger("kioskctl")

static_dir = Path(__file__).with_name("static")


def _cfg_snapshot() -> dict[str, Any]:
    with cfg_lock:
        return copy.deepcopy(cfg)


def require_auth(x_api_key: str | None = Header(default=None)) -> None:
    current = _cfg_snapshot()
    auth = current["admin"].get("auth", {})
    if auth.get("enabled", True) and x_api_key != auth.get("token"):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def devtools(config: dict[str, Any] | None = None) -> DevTools:
    current = config or _cfg_snapshot()
    return DevTools(int(current["browser"].get("devtools_port", 9222)), str(current["browser"].get("url", "")))


def status() -> dict[str, Any]:
    current = _cfg_snapshot()
    metrics = system_metrics(current)
    distro = distro_info()
    dt = devtools(current)
    browser_running = dt.available()
    try:
        url = dt.current_url()
    except Exception:
        url = current["browser"]["url"]
    try:
        executable = chromium_executable(str(current["browser"].get("executable", "auto")))
        provider = browser_provider(current)
        profile = str(resolved_user_data_dir(current))
    except Exception:
        executable = str(current["browser"].get("executable", "auto"))
        provider = str(current["browser"].get("provider", "auto"))
        profile = str(current["browser"].get("user_data_dir", "auto"))
    tools = WaylandTools(current)
    audio = tools.audio_status()
    try:
        viewport = dt.viewport_details() if browser_running else None
    except Exception:
        viewport = None
    output_details = tools.output_details()
    geometry = tools.geometry_status(viewport, output_details)
    inputs = input_devices()
    return {
        "version": APP_VERSION,
        "device_name": current["device"]["name"],
        "distro": distro,
        "browser_active": browser_running,
        "kiosk_enabled": kiosk_enabled(current),
        "browser_provider": provider,
        "browser_executable": executable,
        "browser_profile": profile,
        "browser_prompts": current["browser"].get("prompts", {}),
        "browser_experience": {
            "pages": copy.deepcopy(current["browser"].get("pages", [])),
            "zoom": current["browser"].get("zoom", 1.0),
            "color_scheme": current["browser"].get("color_scheme", "auto"),
            "touch_ui": copy.deepcopy(current["browser"].get("touch_ui", {})),
        },
        "configured_url": current["browser"]["url"],
        "current_url": url,
        "current_page": _current_page_name(current, url),
        "pages": _page_choices(current),
        "outputs": [str(x.get("name")) for x in output_details],
        "output_details": output_details,
        "display_config": current.get("display", {}),
        "wayland_display": tools.wayland_display(),
        "display_source": tools.display_source(),
        "geometry": geometry,
        "viewport": viewport,
        "input_devices": inputs,
        "input_config": current.get("input", {}),
        "touch_mapping": touch_mapping_status(current),
        "touch_pointer_suppression": touch_pointer_suppression_status(current),
        "touchpad_suppression": touchpad_suppression_status(current),
        "audio": audio,
        "audio_provider": audio.get("provider"),
        "volume": audio.get("volume"),
        "brightness": tools.get_brightness(),
        "mqtt_enabled": bool(current["mqtt"].get("enabled")),
        "mqtt": mqtt_bridge.status() if "mqtt_bridge" in globals() else {"enabled": bool(current["mqtt"].get("enabled"))},
        "plugins": plugin_manager.status() if "plugin_manager" in globals() else {},
        "plugin_manifests": plugin_manager.manifests() if "plugin_manager" in globals() else {},
        "plugin_catalog": plugin_manager.catalog() if "plugin_manager" in globals() else [],
        "idle": idle_manager.status() if "idle_manager" in globals() else copy.deepcopy(current.get("idle", {})),
        "screensaver": {
            **copy.deepcopy(current.get("screensaver", {})),
            "images": _screensaver_images(current),
            "active": bool(idle_manager.status().get("screensaver_active")) if "idle_manager" in globals() else False,
            "provider": idle_manager.status().get("screensaver_provider", "core") if "idle_manager" in globals() else "core",
            "provider_name": idle_manager.status().get("screensaver_provider_name", "Simple screensaver") if "idle_manager" in globals() else "Simple screensaver",
        },
        "monitoring": copy.deepcopy(current.get("monitoring", {})),
        **metrics,
    }


def _set_url_action(url: str) -> dict[str, Any]:
    if not url.startswith(("http://", "https://", "file://")):
        raise ValueError("URL must begin with http://, https://, or file://")
    with cfg_lock:
        cfg["browser"]["url"] = url
        save_config(cfg, CONFIG_PATH)
    try:
        devtools().navigate(url)
        mode = "navigated"
    except Exception:
        try:
            restart_kiosk_session()
            mode = "browser_restarted"
        except Exception:
            mode = "saved_kiosk_not_running"
    event_bus.emit("browser.url_changed", url=url, mode=mode) if "event_bus" in globals() else None
    return {"ok": True, "url": url, "mode": mode}


def _browser_reload_action() -> dict[str, Any]:
    try:
        devtools().reload()
        if "event_bus" in globals(): event_bus.emit("browser.reloaded", mode="devtools")
        return {"ok": True, "mode": "devtools"}
    except Exception:
        try:
            restart_kiosk_session()
            return {"ok": True, "mode": "browser_restarted"}
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc


def _page_choices(config: dict[str, Any]) -> list[dict[str, str]]:
    browser = config.get("browser", {})
    pages = [{"name": "Home", "url": str(browser.get("url", "https://example.com"))}]
    for item in browser.get("pages", []):
        if isinstance(item, dict) and item.get("url"):
            name = str(item.get("name") or f"Page {len(pages) + 1}")
            if name.casefold() == "home":
                name = "Home (page)"
            pages.append({"name": name, "url": str(item["url"])})
    return pages


def _current_page_name(config: dict[str, Any], url: str) -> str:
    for item in _page_choices(config):
        candidate = item["url"]
        if url == candidate or (candidate and url.startswith(candidate)):
            return item["name"]
    return "Custom"


def _navigate_page(value: str, *, relative: int | None = None) -> dict[str, Any]:
    current = _cfg_snapshot()
    pages = _page_choices(current)
    if not pages:
        raise ValueError("no configured pages")
    if relative is not None:
        try:
            here = devtools(current).current_url()
        except Exception:
            here = str(current.get("browser", {}).get("url", ""))
        index = 0
        for i, item in enumerate(pages):
            if here == item["url"] or here.startswith(item["url"]):
                index = i
                break
        target = pages[(index + relative) % len(pages)]
    else:
        wanted = value.strip()
        target = next((item for item in pages if item["name"].casefold() == wanted.casefold()), None)
        if target is None and wanted.startswith(("http://", "https://", "file://")):
            target = {"name": "Custom", "url": wanted}
        if target is None:
            raise ValueError(f"unknown configured page: {wanted}")
    devtools(current).navigate(target["url"])
    if "event_bus" in globals():
        event_bus.emit("browser.navigated", url=target["url"], page=target["name"])
    return {"ok": True, **target}


ALLOWED_SCREENSAVER_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_SCREENSAVER_IMAGE_BYTES = 15 * 1024 * 1024


def _screensaver_dir(config: dict[str, Any] | None = None) -> Path:
    current = config or _cfg_snapshot()
    path = Path(str(current.get("screensaver", {}).get("image_dir", "/var/lib/kioskctl/screensaver")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_screensaver_name(name: str) -> str:
    raw = Path(str(name or "image")).name
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", raw).strip(" .") or "image"
    suffix = Path(stem).suffix.lower()
    if suffix not in ALLOWED_SCREENSAVER_EXTENSIONS:
        raise ValueError("screensaver image must be PNG, JPG, JPEG, WEBP, or GIF")
    return stem[:180]


def _screensaver_images(config: dict[str, Any] | None = None) -> list[str]:
    try:
        root = _screensaver_dir(config)
        return sorted(
            p.name for p in root.iterdir()
            if p.is_file() and p.suffix.lower() in ALLOWED_SCREENSAVER_EXTENSIONS
        )
    except Exception:
        return []


def _local_request(request: Request) -> bool:
    host = str(request.client.host if request.client else "")
    return host in {"127.0.0.1", "::1", "localhost"}


def mqtt_command(command: str, payload: str) -> None:
    """Generic kioskctl MQTT command surface used by integrations and users."""
    current = _cfg_snapshot()
    command = command.strip().lower()
    value = payload.strip()
    if command == "reload":
        _browser_reload_action()
    elif command == "restart_browser":
        restart_kiosk_session()
        event_bus.emit("browser.restarted", source="mqtt") if "event_bus" in globals() else None
    elif command == "reboot":
        power_action("reboot", current["system"].get("allow_power_actions", True))
    elif command == "screen":
        on = value.lower() in {"on", "1", "true"}
        WaylandTools(current).display_power(on)
        event_bus.emit("display.power", on=on) if "event_bus" in globals() else None
    elif command == "brightness":
        percent = max(1, min(100, int(float(value))))
        WaylandTools(current).set_brightness(percent)
        event_bus.emit("display.brightness_changed", percent=percent) if "event_bus" in globals() else None
    elif command == "volume":
        percent = max(0, min(100, int(float(value))))
        WaylandTools(current).set_volume(percent)
        event_bus.emit("audio.volume_changed", percent=percent) if "event_bus" in globals() else None
    elif command == "url":
        _set_url_action(value)
    elif command == "rotation":
        if value not in {"normal", "90", "180", "270"}:
            raise ValueError("rotation must be normal, 90, 180, or 270")
        with cfg_lock:
            cfg.setdefault("display", {})["transform"] = value
            save_config(cfg, CONFIG_PATH)
        current = _cfg_snapshot()
        install_touch_transform(current)
        if kiosk_enabled(current):
            restart_kiosk_session()
        else:
            WaylandTools(current).reinitialize_display()
        event_bus.emit("display.rotation_changed", transform=value) if "event_bus" in globals() else None
    elif command == "reinitialize_display":
        WaylandTools(current).reinitialize_display()
        event_bus.emit("display.reinitialized") if "event_bus" in globals() else None
    elif command == "page":
        _navigate_page(value)
    elif command == "next_page":
        _navigate_page("", relative=1)
    elif command == "previous_page":
        _navigate_page("", relative=-1)
    elif command == "zoom":
        zoom = float(value)
        if not 0.5 <= zoom <= 2.0:
            raise ValueError("zoom must be between 0.5 and 2.0")
        with cfg_lock:
            cfg.setdefault("browser", {})["zoom"] = zoom
            save_config(cfg, CONFIG_PATH)
        updated = _cfg_snapshot()
        try:
            devtools(updated).install_runtime_features(updated)
        except Exception:
            pass
        event_bus.emit("browser.experience_changed", zoom=zoom)
    elif command in {"theme", "color_scheme"}:
        scheme = value.lower()
        if scheme not in {"auto", "light", "dark"}:
            raise ValueError("theme must be auto, light, or dark")
        with cfg_lock:
            cfg.setdefault("browser", {})["color_scheme"] = scheme
            save_config(cfg, CONFIG_PATH)
        updated = _cfg_snapshot()
        try:
            if kiosk_enabled(updated):
                restart_kiosk_session()
            else:
                devtools(updated).set_color_scheme(scheme)
        except Exception:
            pass
        event_bus.emit("browser.color_scheme_changed", color_scheme=scheme)
    elif command == "idle":
        enabled = value.lower() in {"on", "1", "true", "enabled"}
        with cfg_lock:
            cfg.setdefault("idle", {})["enabled"] = enabled
            save_config(cfg, CONFIG_PATH)
        if not enabled and "idle_manager" in globals():
            idle_manager.wake("mqtt-idle-disabled")
        event_bus.emit("idle.config_changed", enabled=enabled)
    else:
        raise ValueError(f"unsupported MQTT command: {command}")


class MQTTConfigBody(BaseModel):
    enabled: bool | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    base_topic: str | None = None


class HomeAssistantConfigBody(BaseModel):
    enabled: bool | None = None
    discovery_prefix: str | None = None


class BrowserPageBody(BaseModel):
    name: str
    url: str


class BrowserExperienceBody(BaseModel):
    zoom: float | None = None
    color_scheme: str | None = None
    pages: list[BrowserPageBody] | None = None
    pull_to_refresh: bool | None = None
    pull_threshold_px: int | None = None
    edge_drawer: bool | None = None
    onscreen_keyboard: bool | None = None


class BrowserColorSchemeBody(BaseModel):
    color_scheme: str


class MonitoringConfigBody(BaseModel):
    cpu_percent: int | None = None
    memory_percent: int | None = None
    disk_percent: int | None = None
    temperature_c: int | None = None


class IdleConfigBody(BaseModel):
    enabled: bool | None = None
    dim_after_seconds: int | None = None
    off_after_seconds: int | None = None
    dim_brightness: int | None = None
    wake_on_input: bool | None = None


class ScreensaverConfigBody(BaseModel):
    enabled: bool | None = None
    after_seconds: int | None = None
    interval_seconds: int | None = None
    fit: str | None = None
    shuffle: bool | None = None
    background: str | None = None
    keep_display_on: bool | None = None


class ScreensaverImageBody(BaseModel):
    name: str
    data_base64: str


class DigitalSignageConfigBody(BaseModel):
    enabled: bool | None = None
    after_seconds: int | None = None
    interval_seconds: int | None = None
    fit: str | None = None
    shuffle: bool | None = None
    background: str | None = None
    keep_display_on: bool | None = None
    schedule_enabled: bool | None = None
    schedule_start: str | None = None
    schedule_end: str | None = None
    schedule_days: list[int] | None = None


class ImmichConfigBody(BaseModel):
    enabled: bool | None = None
    server_url: str | None = None
    api_key: str | None = None
    album_id: str | None = None
    after_seconds: int | None = None
    interval_seconds: int | None = None
    fit: str | None = None
    background: str | None = None
    keep_display_on: bool | None = None
    random_count: int | None = None


event_bus = EventBus()
mqtt_bridge = MQTTBridge(cfg, status, mqtt_command)
plugin_manager = PluginManager()
digital_signage_plugin = DigitalSignagePlugin(cfg)
immich_plugin = ImmichPlugin(cfg)
homeassistant_plugin = HomeAssistantPlugin(cfg, mqtt_bridge, event_bus, status, APP_VERSION)
plugin_manager.register(digital_signage_plugin)
plugin_manager.register(immich_plugin)
plugin_manager.register(homeassistant_plugin)
idle_manager = IdleManager(_cfg_snapshot, plugin_manager.screensaver_provider)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Plugins register transport subscriptions/listeners first; MQTT then
    # connects and delivers its connection event to enabled integrations.
    plugin_manager.start()
    mqtt_bridge.start()
    idle_manager.start()
    try:
        yield
    finally:
        idle_manager.stop()
        mqtt_bridge.stop()
        plugin_manager.stop()


app = FastAPI(title="kioskctl", version=APP_VERSION, docs_url="/api/docs", redoc_url=None, lifespan=lifespan)

@app.middleware("http")
async def no_cache_admin_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response

app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def root():
    return FileResponse(static_dir / "index.html")


@app.get("/screensaver", response_class=HTMLResponse)
def screensaver_page(request: Request):
    if not _local_request(request):
        raise HTTPException(403, "Local kiosk only")
    current = _cfg_snapshot()
    sc = current.get("screensaver", {})
    images = _screensaver_images(current)
    interval_ms = max(2000, int(sc.get("interval_seconds", 10) or 10) * 1000)
    fit = "cover" if str(sc.get("fit", "contain")) == "cover" else "contain"
    background = str(sc.get("background", "#000000") or "#000000")
    shuffle = bool(sc.get("shuffle", False))
    import json as _json
    urls_json = _json.dumps([f"/screensaver/image/{quote(name)}" for name in images])
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:{background};cursor:none}}body{{display:grid;place-items:center}}#slide{{width:100%;height:100%;object-fit:{fit};opacity:1;transition:opacity .6s ease}}#empty{{font:600 26px system-ui;color:#94a3b8;text-align:center}}</style></head>
<body><img id="slide" alt="" hidden><div id="empty">kioskctl</div><script>
let images={urls_json};const shuffle={str(shuffle).lower()};if(shuffle)images=images.sort(()=>Math.random()-.5);let i=0;const img=document.getElementById('slide'),empty=document.getElementById('empty');
function show(){{if(!images.length)return;empty.hidden=true;img.hidden=false;img.src=images[i%images.length]+'?v='+Date.now();i++;}}show();if(images.length>1)setInterval(()=>{{img.style.opacity='0';setTimeout(()=>{{show();img.style.opacity='1';}},650)}},{interval_ms});
</script></body></html>"""
    return HTMLResponse(page)


@app.get("/screensaver/image/{name}")
def screensaver_local_image(name: str, request: Request):
    if not _local_request(request):
        raise HTTPException(403, "Local kiosk only")
    try:
        safe = _safe_screensaver_name(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    path = _screensaver_dir() / safe
    if not path.is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})




@app.get("/plugin/digital-signage/screen", response_class=HTMLResponse)
def digital_signage_screen(request: Request):
    if not _local_request(request):
        raise HTTPException(403, "Local kiosk only")
    c = digital_signage_plugin.config()
    images = digital_signage_plugin.assets()
    interval_ms = max(2000, int(c.get("interval_seconds", 10) or 10) * 1000)
    fit = "cover" if str(c.get("fit", "cover")) == "cover" else "contain"
    background = str(c.get("background", "#000000") or "#000000")
    shuffle = bool(c.get("shuffle", False))
    import json as _json
    urls_json = _json.dumps([f"/plugin/digital-signage/asset/{quote(name)}" for name in images])
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:{background};cursor:none}}body{{display:grid;place-items:center}}#slide{{width:100%;height:100%;object-fit:{fit};opacity:1;transition:opacity .6s ease}}#empty{{font:600 26px system-ui;color:#94a3b8;text-align:center}}</style></head>
<body><img id="slide" alt="" hidden><div id="empty">Digital Signage<br><small>No images uploaded</small></div><script>
let images={urls_json};const shuffle={str(shuffle).lower()};if(shuffle)images=images.sort(()=>Math.random()-.5);let i=0;const img=document.getElementById('slide'),empty=document.getElementById('empty');
function show(){{if(!images.length)return;empty.hidden=true;img.hidden=false;img.src=images[i%images.length]+'?v='+Date.now();i++;}}show();if(images.length>1)setInterval(()=>{{img.style.opacity='0';setTimeout(()=>{{show();img.style.opacity='1';}},650)}},{interval_ms});
</script></body></html>"""
    return HTMLResponse(page)


@app.get("/plugin/digital-signage/asset/{name}")
def digital_signage_asset(name: str, request: Request):
    if not _local_request(request):
        raise HTTPException(403, "Local kiosk only")
    try:
        safe = digital_signage_plugin.safe_name(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    path = digital_signage_plugin.asset_dir() / safe
    if not path.is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@app.get("/plugin/immich/screen", response_class=HTMLResponse)
def immich_screen(request: Request):
    if not _local_request(request):
        raise HTTPException(403, "Local kiosk only")
    c = immich_plugin.config()
    try:
        assets = immich_plugin.refresh_assets()
        error = ""
    except Exception as exc:
        assets = []
        error = html.escape(str(exc))
    interval_ms = max(2000, int(c.get("interval_seconds", 15) or 15) * 1000)
    fit = "cover" if str(c.get("fit", "contain")) == "cover" else "contain"
    background = str(c.get("background", "#000000") or "#000000")
    import json as _json
    urls_json = _json.dumps([f"/plugin/immich/image/{quote(str(item['id']))}" for item in assets])
    error_json = _json.dumps(error)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:{background};cursor:none}}#stage{{position:fixed;inset:0;overflow:hidden;background:{background}}}#slide{{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);max-width:none;max-height:none;object-fit:fill;opacity:1;transition:opacity .6s ease}}#slide[hidden],#empty[hidden]{{display:none!important}}#empty{{position:fixed;inset:0;display:grid;place-items:center;font:600 24px system-ui;color:#94a3b8;text-align:center;padding:10vw;box-sizing:border-box}}</style></head>
<body><div id="stage"><img id="slide" alt="" hidden><div id="empty">Loading Immich photos…</div></div><script>
const fitMode={_json.dumps(fit)};let images={urls_json};let error={error_json};let i=0;const img=document.getElementById('slide'),empty=document.getElementById('empty');if(error)empty.textContent='Immich: '+error;
function fitImage(){{if(!img.naturalWidth||!img.naturalHeight)return;const vw=window.innerWidth,vh=window.innerHeight,iw=img.naturalWidth,ih=img.naturalHeight;const scale=fitMode==='cover'?Math.max(vw/iw,vh/ih):Math.min(vw/iw,vh/ih);img.style.width=Math.max(1,Math.round(iw*scale))+'px';img.style.height=Math.max(1,Math.round(ih*scale))+'px';}}
img.addEventListener('load',()=>{{empty.hidden=true;img.hidden=false;fitImage();}});img.addEventListener('error',()=>{{img.hidden=true;empty.hidden=false;empty.textContent='Unable to load Immich image';}});window.addEventListener('resize',fitImage);
function show(){{if(!images.length)return;img.src=images[i%images.length]+'?v='+Date.now();i++;}}show();if(images.length>1)setInterval(()=>{{img.style.opacity='0';setTimeout(()=>{{show();img.style.opacity='1';}},650)}},{interval_ms});
</script></body></html>"""
    return HTMLResponse(page)


@app.get("/plugin/immich/image/{asset_id}")
def immich_image(asset_id: str, request: Request):
    if not _local_request(request):
        raise HTTPException(403, "Local kiosk only")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", str(asset_id)):
        raise HTTPException(404, "Invalid asset id")
    try:
        raw, content_type = immich_plugin.proxy_image(asset_id)
    except Exception as exc:
        raise HTTPException(502, str(exc))
    return Response(content=raw, media_type=content_type, headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION, "device_name": cfg["device"]["name"]}


@app.get("/api/status", dependencies=[Depends(require_auth)])
def api_status():
    return status()


@app.get("/api/diagnostics", dependencies=[Depends(require_auth)])
def api_diagnostics():
    report = diagnostic_report(_cfg_snapshot())
    m = mqtt_bridge.status()
    if m.get("enabled"):
        check = {"id": "mqtt", "ok": bool(m.get("connected")), "message": f"{m.get('host')}:{m.get('port')}" + (" connected" if m.get("connected") else f" — {m.get('last_error') or 'not connected'}")}
        report["checks"].append(check)
        report["summary"]["ok" if check["ok"] else "warnings"] += 1
    report["mqtt"] = m
    report["plugins"] = plugin_manager.status()
    return report


@app.get("/api/mqtt/status", dependencies=[Depends(require_auth)])
def api_mqtt_status():
    return mqtt_bridge.status()


@app.post("/api/mqtt/config", dependencies=[Depends(require_auth)])
def api_mqtt_config(body: MQTTConfigBody):
    data = body.model_dump(exclude_none=True)
    password = data.pop("password", None)
    if "host" in data and not str(data["host"]).strip():
        raise HTTPException(400, "MQTT host cannot be blank")
    if "port" in data and not 1 <= int(data["port"]) <= 65535:
        raise HTTPException(400, "MQTT port must be between 1 and 65535")
    if "base_topic" in data and not str(data["base_topic"]).strip(" /"):
        raise HTTPException(400, "MQTT base topic cannot be blank")
    # Stop while the old broker/topic values are still active so the retained
    # old availability topic receives an offline state before a move.
    mqtt_bridge.stop()
    with cfg_lock:
        target = cfg.setdefault("mqtt", {})
        target.update(data)
        if password not in (None, ""):
            target["password"] = password
        save_config(cfg, CONFIG_PATH)
    mqtt_bridge.start()
    event_bus.emit("mqtt.config_changed", enabled=bool(cfg["mqtt"].get("enabled")))
    return mqtt_bridge.status()


@app.get("/api/plugins", dependencies=[Depends(require_auth)])
def api_plugins():
    return {"plugins": plugin_manager.status(), "manifests": plugin_manager.manifests()}


@app.get("/api/plugins/manifests", dependencies=[Depends(require_auth)])
def api_plugin_manifests():
    return {"manifests": plugin_manager.manifests()}




@app.get("/api/plugins/catalog", dependencies=[Depends(require_auth)])
def api_plugin_catalog():
    return {"plugins": plugin_manager.catalog()}


def _set_optional_plugin_installed(plugin_id: str, installed: bool) -> dict[str, Any]:
    if plugin_id not in {"digital_signage", "immich"}:
        raise HTTPException(400, "Only optional catalog plugins can be installed or removed")
    plugin = plugin_manager.get(plugin_id)
    if plugin is None:
        raise HTTPException(404, "Plugin not found")
    with cfg_lock:
        target = cfg.setdefault("plugins", {}).setdefault(plugin_id, {})
        target["installed"] = bool(installed)
        if not installed:
            target["enabled"] = False
        save_config(cfg, CONFIG_PATH)
    if installed:
        plugin.start()
    else:
        if idle_manager.status().get("screensaver_provider") == plugin_id:
            idle_manager.stop_screensaver("plugin-removed")
        plugin.stop()
    event_bus.emit("plugin.install_changed", plugin=plugin_id, installed=bool(installed))
    return plugin.status()


@app.post("/api/plugins/{plugin_id}/install", dependencies=[Depends(require_auth)])
def api_plugin_install(plugin_id: str):
    return {"ok": True, "plugin": _set_optional_plugin_installed(plugin_id, True)}


@app.delete("/api/plugins/{plugin_id}", dependencies=[Depends(require_auth)])
def api_plugin_remove(plugin_id: str):
    return {"ok": True, "plugin": _set_optional_plugin_installed(plugin_id, False)}


def _disable_competing_screensavers(active_id: str) -> None:
    """Keep one idle-content provider authoritative at a time."""
    with cfg_lock:
        cfg.setdefault("screensaver", {})["enabled"] = False
        for plugin_id in ("digital_signage", "immich"):
            if plugin_id != active_id:
                cfg.setdefault("plugins", {}).setdefault(plugin_id, {})["enabled"] = False
        save_config(cfg, CONFIG_PATH)
    if idle_manager.status().get("screensaver_active"):
        idle_manager.stop_screensaver("screensaver-provider-changed")


@app.get("/api/plugins/digital_signage/assets", dependencies=[Depends(require_auth)])
def digital_signage_assets():
    return {"images": digital_signage_plugin.assets(), "plugin": digital_signage_plugin.status()}


@app.post("/api/plugins/digital_signage/config", dependencies=[Depends(require_auth)])
def digital_signage_config(body: DigitalSignageConfigBody):
    data = body.model_dump(exclude_none=True)
    if not digital_signage_plugin.installed:
        raise HTTPException(409, "Install the Digital Signage plugin first")
    if "fit" in data and data["fit"] not in {"contain", "cover"}:
        raise HTTPException(400, "fit must be contain or cover")
    for key in ("schedule_start", "schedule_end"):
        if key in data and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(data[key])):
            raise HTTPException(400, f"{key} must be HH:MM")
    if "schedule_days" in data:
        days = sorted({int(x) for x in data["schedule_days"]})
        if any(x < 0 or x > 6 for x in days):
            raise HTTPException(400, "schedule_days must contain values 0 through 6")
        data["schedule_days"] = days
    with cfg_lock:
        target = cfg.setdefault("plugins", {}).setdefault("digital_signage", {})
        target.update(data)
        save_config(cfg, CONFIG_PATH)
    if bool(data.get("enabled")):
        _disable_competing_screensavers("digital_signage")
    elif idle_manager.status().get("screensaver_provider") == "digital_signage":
        idle_manager.stop_screensaver("digital-signage-disabled")
    event_bus.emit("plugin.config_changed", plugin="digital_signage", enabled=digital_signage_plugin.enabled)
    return {"ok": True, "plugin": digital_signage_plugin.status()}


@app.post("/api/plugins/digital_signage/assets", dependencies=[Depends(require_auth)])
def digital_signage_upload(body: ScreensaverImageBody):
    if not digital_signage_plugin.installed:
        raise HTTPException(409, "Install the Digital Signage plugin first")
    try:
        name = digital_signage_plugin.safe_name(body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    encoded = str(body.data_base64 or "")
    if "," in encoded and encoded.lower().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise HTTPException(400, "Invalid base64 image data") from exc
    if not raw or len(raw) > MAX_SCREENSAVER_IMAGE_BYTES:
        raise HTTPException(400, "Image must be between 1 byte and 15 MiB")
    path = digital_signage_plugin.asset_dir() / name
    path.write_bytes(raw)
    os.chmod(path, 0o644)
    return {"ok": True, "name": name, "bytes": len(raw), "images": digital_signage_plugin.assets()}


@app.delete("/api/plugins/digital_signage/assets/{name}", dependencies=[Depends(require_auth)])
def digital_signage_delete(name: str):
    try:
        safe = digital_signage_plugin.safe_name(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    path = digital_signage_plugin.asset_dir() / safe
    if path.exists():
        path.unlink()
    return {"ok": True, "images": digital_signage_plugin.assets()}


@app.post("/api/plugins/digital_signage/preview", dependencies=[Depends(require_auth)])
def digital_signage_preview():
    if not digital_signage_plugin.installed:
        raise HTTPException(409, "Install the Digital Signage plugin first")
    if not digital_signage_plugin.assets():
        raise HTTPException(409, "Upload at least one signage image first")
    idle_manager.preview_screensaver(digital_signage_plugin)
    return {"ok": True, "active": True}


@app.post("/api/plugins/immich/config", dependencies=[Depends(require_auth)])
def immich_config(body: ImmichConfigBody):
    data = body.model_dump(exclude_none=True)
    if not immich_plugin.installed:
        raise HTTPException(409, "Install the Immich plugin first")
    api_key = data.pop("api_key", None)
    if "server_url" in data:
        server = str(data["server_url"] or "").strip().rstrip("/")
        if server and not server.startswith(("http://", "https://")):
            raise HTTPException(400, "Immich server URL must begin with http:// or https://")
        data["server_url"] = server
    if "fit" in data and data["fit"] not in {"contain", "cover"}:
        raise HTTPException(400, "fit must be contain or cover")
    with cfg_lock:
        target = cfg.setdefault("plugins", {}).setdefault("immich", {})
        target.update(data)
        if api_key not in (None, ""):
            target["api_key"] = api_key
        save_config(cfg, CONFIG_PATH)
    if bool(data.get("enabled")):
        _disable_competing_screensavers("immich")
    elif idle_manager.status().get("screensaver_provider") == "immich":
        idle_manager.stop_screensaver("immich-disabled")
    event_bus.emit("plugin.config_changed", plugin="immich", enabled=immich_plugin.enabled)
    return {"ok": True, "plugin": immich_plugin.status()}


@app.post("/api/plugins/immich/test", dependencies=[Depends(require_auth)])
def immich_test():
    if not immich_plugin.installed:
        raise HTTPException(409, "Install the Immich plugin first")
    try:
        return immich_plugin.test_connection()
    except Exception as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/plugins/immich/preview", dependencies=[Depends(require_auth)])
def immich_preview():
    if not immich_plugin.installed:
        raise HTTPException(409, "Install the Immich plugin first")
    try:
        if not immich_plugin.refresh_assets(force=True):
            raise HTTPException(409, "Immich returned no images")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(409, str(exc))
    idle_manager.preview_screensaver(immich_plugin)
    return {"ok": True, "active": True}


@app.post("/api/plugins/homeassistant/config", dependencies=[Depends(require_auth)])
def api_homeassistant_config(body: HomeAssistantConfigBody):
    data = body.model_dump(exclude_none=True)
    was_enabled = homeassistant_plugin.enabled
    old_prefix = homeassistant_plugin.prefix
    new_prefix = str(data.get("discovery_prefix", old_prefix) or old_prefix)
    if was_enabled and (data.get("enabled") is False or new_prefix != old_prefix):
        homeassistant_plugin.clear_discovery()
    with cfg_lock:
        target = cfg.setdefault("plugins", {}).setdefault("homeassistant", {})
        if "discovery_prefix" in data and not str(data["discovery_prefix"]).strip(" /"):
            raise HTTPException(400, "Discovery prefix cannot be blank")
        target.update(data)
        save_config(cfg, CONFIG_PATH)
    result = homeassistant_plugin.publish_discovery() if homeassistant_plugin.enabled and mqtt_bridge.connected else {"ok": True}
    event_bus.emit("plugin.config_changed", plugin="homeassistant", enabled=homeassistant_plugin.enabled)
    return {"plugin": homeassistant_plugin.status(), "publish": result}


@app.post("/api/plugins/homeassistant/republish", dependencies=[Depends(require_auth)])
def api_homeassistant_republish():
    result = homeassistant_plugin.publish_discovery()
    if not result.get("ok"):
        raise HTTPException(409, result.get("reason", "Unable to publish Home Assistant discovery"))
    return result


@app.get("/api/temperature/sensors", dependencies=[Depends(require_auth)])
def api_temperature_sensors():
    return {"sensors": temperature_sensors(), "primary": cfg.get("temperature", {}).get("primary", "auto")}

@app.get("/api/input/devices", dependencies=[Depends(require_auth)])
def api_input_devices():
    return {"devices": input_devices()}


class URLBody(BaseModel):
    url: str


class PercentBody(BaseModel):
    percent: int


class ClickBody(BaseModel):
    x: float
    y: float


class TextBody(BaseModel):
    text: str


class KeyBody(BaseModel):
    key: str


class DisplayConfigBody(BaseModel):
    output: str | None = None
    mode: str | None = None
    refresh_hz: float | str | None = None
    scale: float | None = None
    transform: str | None = None
    rotate_touch_with_display: bool | None = None
    ignore_touch_mouse_emulation: bool | None = None
    disable_touchpad_in_kiosk: bool | None = None


class InputConfigBody(BaseModel):
    rotate_touch_with_display: bool | None = None
    ignore_touch_mouse_emulation: bool | None = None
    disable_touchpad_in_kiosk: bool | None = None


class PromptConfigBody(BaseModel):
    password_manager: bool | None = None
    notifications: str | None = None
    translate: bool | None = None
    autofill: bool | None = None


@app.post("/api/kiosk/enable", dependencies=[Depends(require_auth)])
def kiosk_enable():
    try:
        enable_kiosk_session()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "enabled": True}


@app.post("/api/kiosk/disable", dependencies=[Depends(require_auth)])
def kiosk_disable():
    try:
        disable_kiosk_session()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "enabled": False}


@app.post("/api/browser/url", dependencies=[Depends(require_auth)])
def set_url(body: URLBody):
    try:
        return _set_url_action(body.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/browser/navigate", dependencies=[Depends(require_auth)])
def browser_navigate(body: URLBody):
    try:
        return _navigate_page(body.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/browser/experience", dependencies=[Depends(require_auth)])
def browser_experience(body: BrowserExperienceBody):
    data = body.model_dump(exclude_none=True)
    pages = data.pop("pages", None)
    before_pages = copy.deepcopy(_cfg_snapshot().get("browser", {}).get("pages", []))
    touch_keys = {"pull_to_refresh", "pull_threshold_px", "edge_drawer", "onscreen_keyboard"}
    with cfg_lock:
        browser = cfg.setdefault("browser", {})
        if "zoom" in data:
            browser["zoom"] = data.pop("zoom")
        if "color_scheme" in data:
            browser["color_scheme"] = data.pop("color_scheme")
        if pages is not None:
            browser["pages"] = pages
        touch = browser.setdefault("touch_ui", {})
        for key in list(data):
            if key in touch_keys:
                touch[key] = data.pop(key)
        try:
            save_config(cfg, CONFIG_PATH)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    current = _cfg_snapshot()
    restarted = False
    if kiosk_enabled(current):
        try:
            restart_kiosk_session()
            restarted = True
        except Exception as exc:
            raise HTTPException(409, f"settings saved but browser restart failed: {exc}")
    else:
        try:
            devtools(current).install_runtime_features(current)
        except Exception:
            pass
    pages_changed = before_pages != current.get("browser", {}).get("pages", [])
    event_bus.emit("browser.experience_changed", restarted=restarted, pages_changed=pages_changed)
    return {"ok": True, "experience": status().get("browser_experience"), "restarted": restarted}


@app.post("/api/browser/color-scheme", dependencies=[Depends(require_auth)])
def browser_color_scheme(body: BrowserColorSchemeBody):
    scheme = str(body.color_scheme or "auto").lower()
    if scheme not in {"auto", "light", "dark"}:
        raise HTTPException(400, "color_scheme must be auto, light, or dark")
    with cfg_lock:
        cfg.setdefault("browser", {})["color_scheme"] = scheme
        try:
            save_config(cfg, CONFIG_PATH)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    applied = False
    restarted = False
    current = _cfg_snapshot()
    if kiosk_enabled(current):
        try:
            restart_kiosk_session()
            restarted = True
            applied = True
        except Exception as exc:
            raise HTTPException(409, f"theme saved but browser restart failed: {exc}")
    else:
        try:
            devtools(current).set_color_scheme(scheme)
            applied = True
        except Exception:
            pass
    event_bus.emit("browser.color_scheme_changed", color_scheme=scheme, restarted=restarted)
    return {"ok": True, "color_scheme": scheme, "applied": applied, "restarted": restarted}


@app.post("/api/browser/reload", dependencies=[Depends(require_auth)])
def browser_reload():
    try:
        return _browser_reload_action()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/browser/back", dependencies=[Depends(require_auth)])
def browser_back():
    devtools().back()
    return {"ok": True}


@app.post("/api/browser/restart", dependencies=[Depends(require_auth)])
def browser_restart():
    try:
        restart_kiosk_session()
        event_bus.emit("browser.restarted", source="api")
    except Exception as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True}


@app.post("/api/browser/prompts", dependencies=[Depends(require_auth)])
def browser_prompts(body: PromptConfigBody):
    with cfg_lock:
        prompts = cfg["browser"].setdefault("prompts", {})
        for key, value in body.model_dump(exclude_none=True).items():
            if key == "notifications" and str(value) not in {"block", "ask", "allow"}:
                raise HTTPException(400, "notifications must be block, ask, or allow")
            prompts[key] = value
        save_config(cfg, CONFIG_PATH)
        prompt_result = copy.deepcopy(prompts)
    try:
        policy_path = write_managed_policy(_cfg_snapshot())
    except Exception as exc:
        policy_path = f"error: {exc}"
    restarted = False
    if kiosk_enabled(cfg):
        try:
            restart_kiosk_session()
            restarted = True
        except Exception:
            pass
    return {"ok": True, "prompts": prompt_result, "restarted": restarted, "managed_policy": policy_path}


@app.post("/api/input/click", dependencies=[Depends(require_auth)])
def input_click(body: ClickBody):
    if not (0 <= body.x <= 1 and 0 <= body.y <= 1):
        raise HTTPException(400, "x and y must be normalized values from 0 to 1")
    focus = devtools().click_normalized(body.x, body.y)
    idle_manager.notify_activity("remote-click")
    return {"ok": True, "focus": focus}


@app.get("/api/input/focus", dependencies=[Depends(require_auth)])
def input_focus():
    return {"focus": devtools().focus_info()}


@app.post("/api/input/text", dependencies=[Depends(require_auth)])
def input_text(body: TextBody):
    result = devtools().insert_text(body.text)
    idle_manager.notify_activity("remote-text")
    return {"ok": True, **result}


@app.post("/api/input/key", dependencies=[Depends(require_auth)])
def input_key(body: KeyBody):
    try:
        devtools().key(body.key)
        idle_manager.notify_activity("remote-key")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.post("/api/input/config", dependencies=[Depends(require_auth)])
def input_config(body: InputConfigBody):
    data = body.model_dump(exclude_none=True)
    before = _cfg_snapshot().get("input", {})
    with cfg_lock:
        cfg.setdefault("input", {}).update(data)
        save_config(cfg, CONFIG_PATH)
    current = _cfg_snapshot()
    mapping = install_touch_transform(current)
    pointer = install_touch_pointer_suppression(current)
    touchpad = install_touchpad_suppression(current)
    restarted = False
    if before != current.get("input", {}) and kiosk_enabled(current):
        try:
            restart_kiosk_session()
            restarted = True
        except Exception as exc:
            msg = f"input rules saved but kiosk restart failed: {exc}"
            mapping["warning"] = msg
            pointer["warning"] = msg
    return {
        "ok": True,
        "config": current.get("input", {}),
        "touch_mapping": mapping,
        "touch_pointer_suppression": pointer,
        "touchpad_suppression": touchpad,
        "session_restarted": restarted,
    }


@app.get("/api/screenshot", dependencies=[Depends(require_auth)])
def screenshot():
    try:
        data = devtools().screenshot_png()
    except Exception as exc:
        raise HTTPException(503, f"Screenshot unavailable: {exc}")
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/display/on", dependencies=[Depends(require_auth)])
def display_on():
    idle_manager.notify_activity("display-on")
    tools = WaylandTools(cfg)
    tools.display_power(True)
    time.sleep(0.2)
    try:
        devtools().notify_geometry_change()
    except Exception:
        pass
    return {"ok": True, "outputs": tools.output_details()}


@app.post("/api/display/off", dependencies=[Depends(require_auth)])
def display_off():
    WaylandTools(cfg).display_power(False, reapply=False)
    return {"ok": True}


@app.post("/api/display/reinitialize", dependencies=[Depends(require_auth)])
def display_reinitialize():
    tools = WaylandTools(cfg)
    result = tools.reinitialize_display()
    try:
        devtools().notify_geometry_change()
    except Exception:
        pass
    return {"ok": True, **result}


@app.post("/api/display/config", dependencies=[Depends(require_auth)])
def display_config(body: DisplayConfigBody):
    data = body.model_dump(exclude_none=True)
    rotate_touch = data.pop("rotate_touch_with_display", None)
    ignore_touch_mouse = data.pop("ignore_touch_mouse_emulation", None)
    disable_touchpad = data.pop("disable_touchpad_in_kiosk", None)
    if "scale" in data and not (0.5 <= float(data["scale"]) <= 4.0):
        raise HTTPException(400, "scale must be between 0.5 and 4.0")
    if "transform" in data and str(data["transform"]) not in {"normal", "90", "180", "270", "flipped", "flipped-90", "flipped-180", "flipped-270"}:
        raise HTTPException(400, "unsupported transform")

    before = _cfg_snapshot()
    old_transform = str(before.get("display", {}).get("transform", "normal"))
    old_rotate_touch = bool(before.get("input", {}).get("rotate_touch_with_display", True))
    old_ignore_touch_mouse = bool(before.get("input", {}).get("ignore_touch_mouse_emulation", True))
    old_disable_touchpad = bool(before.get("input", {}).get("disable_touchpad_in_kiosk", False))
    with cfg_lock:
        cfg.setdefault("display", {}).update(data)
        if rotate_touch is not None:
            cfg.setdefault("input", {})["rotate_touch_with_display"] = bool(rotate_touch)
        if ignore_touch_mouse is not None:
            cfg.setdefault("input", {})["ignore_touch_mouse_emulation"] = bool(ignore_touch_mouse)
        if disable_touchpad is not None:
            cfg.setdefault("input", {})["disable_touchpad_in_kiosk"] = bool(disable_touchpad)
        save_config(cfg, CONFIG_PATH)
    current = _cfg_snapshot()
    new_transform = str(current.get("display", {}).get("transform", "normal"))
    new_rotate_touch = bool(current.get("input", {}).get("rotate_touch_with_display", True))
    new_ignore_touch_mouse = bool(current.get("input", {}).get("ignore_touch_mouse_emulation", True))
    new_disable_touchpad = bool(current.get("input", {}).get("disable_touchpad_in_kiosk", False))
    mapping = install_touch_transform(current)
    pointer = install_touch_pointer_suppression(current)
    touchpad = install_touchpad_suppression(current)

    # libinput reads calibration when the device is opened. Restart the
    # graphical session when either display rotation or automatic touch
    # rotation changes so physical coordinates and the output stay aligned.
    if (old_transform != new_transform or old_rotate_touch != new_rotate_touch or old_ignore_touch_mouse != new_ignore_touch_mouse or old_disable_touchpad != new_disable_touchpad) and kiosk_enabled(current):
        try:
            restart_kiosk_session()
            return {"ok": True, "config": current["display"], "input_config": current.get("input", {}), "touch_mapping": mapping, "touch_pointer_suppression": pointer, "touchpad_suppression": touchpad, "session_restarted": True}
        except Exception as exc:
            mapping["warning"] = f"display saved but kiosk restart failed: {exc}"

    try:
        tools = WaylandTools(current)
        dcfg = current.get("display", {})
        needs_reinitialize = (
            str(dcfg.get("transform", "normal")) != "normal"
            or abs(float(dcfg.get("scale", 1.0) or 1.0) - 1.0) > 0.001
            or str(dcfg.get("mode", "preferred")) != "preferred"
            or str(dcfg.get("refresh_hz", "auto")) != "auto"
        )
        # Some wlroots/Cage combinations report a successful transform but do
        # not commit it until the connector is reprobed. Make Apply perform the
        # same reprobe that the manual Reinitialize button used to require.
        result = tools.reinitialize_display() if needs_reinitialize else tools.apply_display_config()
        try:
            devtools(current).notify_geometry_change()
        except Exception:
            pass
        return {"ok": True, "config": current["display"], "input_config": current.get("input", {}), "touch_mapping": mapping, "touch_pointer_suppression": pointer, "touchpad_suppression": touchpad, "session_restarted": False, **result}
    except Exception as exc:
        return {"ok": True, "config": current["display"], "input_config": current.get("input", {}), "touch_mapping": mapping, "touch_pointer_suppression": pointer, "touchpad_suppression": touchpad, "session_restarted": False, "applied": False, "warning": str(exc)}


@app.get("/api/idle/status", dependencies=[Depends(require_auth)])
def idle_status():
    return idle_manager.status()


@app.post("/api/idle/config", dependencies=[Depends(require_auth)])
def idle_config(body: IdleConfigBody):
    data = body.model_dump(exclude_none=True)
    with cfg_lock:
        cfg.setdefault("idle", {}).update(data)
        try:
            save_config(cfg, CONFIG_PATH)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    if not _cfg_snapshot().get("idle", {}).get("enabled", False):
        idle_manager.wake("idle-disabled")
    event_bus.emit("idle.config_changed", **data)
    return {"ok": True, "idle": idle_manager.status()}


@app.get("/api/screensaver/images", dependencies=[Depends(require_auth)])
def screensaver_images():
    current = _cfg_snapshot()
    return {"images": _screensaver_images(current), "config": copy.deepcopy(current.get("screensaver", {})), "active": idle_manager.status().get("screensaver_active", False)}


@app.post("/api/screensaver/config", dependencies=[Depends(require_auth)])
def screensaver_config(body: ScreensaverConfigBody):
    data = body.model_dump(exclude_none=True)
    with cfg_lock:
        cfg.setdefault("screensaver", {}).update(data)
        if bool(data.get("enabled")):
            # The core simple screensaver and plugin signage providers are
            # mutually exclusive. Selecting the simple option disables the
            # optional providers but leaves their configuration installed.
            cfg.setdefault("plugins", {}).setdefault("digital_signage", {})["enabled"] = False
            cfg.setdefault("plugins", {}).setdefault("immich", {})["enabled"] = False
        try:
            save_config(cfg, CONFIG_PATH)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    current = _cfg_snapshot()
    if bool(data.get("enabled")) and idle_manager.status().get("screensaver_active"):
        idle_manager.stop_screensaver("simple-screensaver-selected")
    if not current.get("screensaver", {}).get("enabled", False):
        idle_manager.stop_screensaver("screensaver-disabled")
    event_bus.emit("screensaver.config_changed", **data)
    return {"ok": True, "screensaver": status().get("screensaver", {})}


@app.post("/api/screensaver/images", dependencies=[Depends(require_auth)])
def screensaver_upload(body: ScreensaverImageBody):
    try:
        name = _safe_screensaver_name(body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    encoded = str(body.data_base64 or "")
    if "," in encoded and encoded.lower().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise HTTPException(400, "Invalid base64 image data") from exc
    if not raw or len(raw) > MAX_SCREENSAVER_IMAGE_BYTES:
        raise HTTPException(400, "Image must be between 1 byte and 15 MiB")
    path = _screensaver_dir() / name
    path.write_bytes(raw)
    os.chmod(path, 0o644)
    return {"ok": True, "name": name, "bytes": len(raw), "images": _screensaver_images()}


@app.delete("/api/screensaver/images/{name}", dependencies=[Depends(require_auth)])
def screensaver_delete(name: str):
    try:
        safe = _safe_screensaver_name(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    path = _screensaver_dir() / safe
    if path.exists():
        path.unlink()
    return {"ok": True, "images": _screensaver_images()}


@app.post("/api/screensaver/preview", dependencies=[Depends(require_auth)])
def screensaver_preview():
    if not _screensaver_images():
        raise HTTPException(409, "Upload at least one screensaver image first")
    idle_manager.preview_screensaver()
    return {"ok": True, "active": idle_manager.status().get("screensaver_active", False)}


@app.post("/api/screensaver/stop", dependencies=[Depends(require_auth)])
def screensaver_stop():
    idle_manager.stop_screensaver("api")
    return {"ok": True}


@app.post("/api/monitoring/config", dependencies=[Depends(require_auth)])
def monitoring_config(body: MonitoringConfigBody):
    data = body.model_dump(exclude_none=True)
    limits = {"cpu_percent": (0, 100), "memory_percent": (0, 100), "disk_percent": (0, 100), "temperature_c": (0, 150)}
    for key, value in data.items():
        low, high = limits[key]
        if not low <= int(value) <= high:
            raise HTTPException(400, f"{key} must be between {low} and {high}")
    with cfg_lock:
        thresholds = cfg.setdefault("monitoring", {}).setdefault("thresholds", {})
        thresholds.update(data)
        try:
            save_config(cfg, CONFIG_PATH)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    event_bus.emit("monitoring.thresholds_changed", **data)
    return {"ok": True, "thresholds": copy.deepcopy(_cfg_snapshot().get("monitoring", {}).get("thresholds", {}))}


@app.post("/api/display/brightness", dependencies=[Depends(require_auth)])
def brightness(body: PercentBody):
    # Clamp at the API boundary before touching hardware. Platform providers
    # clamp defensively too, but the route should never pass an invalid value.
    percent = max(1, min(100, int(body.percent)))
    WaylandTools(cfg).set_brightness(percent)
    event_bus.emit("display.brightness_changed", percent=percent)
    return {"ok": True, "percent": percent}


@app.post("/api/audio/volume", dependencies=[Depends(require_auth)])
def volume(body: PercentBody):
    percent = max(0, min(100, int(body.percent)))
    try:
        provider = WaylandTools(cfg).set_volume(percent)
    except Exception as exc:
        raise HTTPException(409, str(exc))
    event_bus.emit("audio.volume_changed", percent=percent)
    return {"ok": True, "percent": percent, "provider": provider}


@app.post("/api/system/reboot", dependencies=[Depends(require_auth)])
def reboot():
    power_action("reboot", cfg["system"].get("allow_power_actions", True))
    return {"ok": True}


@app.post("/api/system/shutdown", dependencies=[Depends(require_auth)])
def shutdown():
    power_action("shutdown", cfg["system"].get("allow_power_actions", True))
    return {"ok": True}


@app.post("/api/system/update", dependencies=[Depends(require_auth)])
def update():
    command = str(cfg.get("update", {}).get("command", "")).strip()
    if not command:
        raise HTTPException(409, "No update command is configured")
    p = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=300)
    if p.returncode:
        logger.error("Configured update failed rc=%s stdout=%r stderr=%r", p.returncode, p.stdout[-4000:], p.stderr[-4000:])
        raise HTTPException(500, "Update failed. Check kioskctl-agent logs for details.")
    return {"ok": True, "output": p.stdout[-2000:]}


def run() -> None:
    import uvicorn
    uvicorn.run(app, host=str(cfg["admin"]["host"]), port=int(cfg["admin"]["port"]))


if __name__ == "__main__":
    run()
