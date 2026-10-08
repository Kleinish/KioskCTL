from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(os.environ.get("KIOSKCTL_CONFIG", "/etc/kioskctl/config.yaml"))
CURRENT_CONFIG_VERSION = 10

DEFAULT_CONFIG: dict[str, Any] = {
    "version": CURRENT_CONFIG_VERSION,
    "device": {"name": "kiosk"},
    "browser": {
        "url": "https://example.com",
        "provider": "auto",
        "executable": "auto",
        "user_data_dir": "auto",
        "incognito": False,
        "devtools_port": 9222,
        "extra_args": [],
        "pages": [],
        "zoom": 1.0,
        "color_scheme": "auto",
        "touch_ui": {
            "pull_to_refresh": True,
            "pull_threshold_px": 110,
            "edge_drawer": False,
            "onscreen_keyboard": False,
        },
        "prompts": {
            "password_manager": False,
            "notifications": "block",
            "translate": False,
            "autofill": False,
        },
    },
    "admin": {
        "host": "0.0.0.0",
        "port": 2324,
        "auth": {"enabled": True, "token": "CHANGE_ME"},
    },
    "system": {
        "kiosk_user": "kioskctl",
        "session_service": "getty@tty1.service",
        "tty": "tty1",
        "runtime_dir": "auto",
        "wayland_display": "auto",
        "allow_power_actions": True,
        "enabled_marker": "/etc/kioskctl/kiosk.enabled",
    },
    "display": {
        "output": "auto",
        "mode": "preferred",
        "refresh_hz": "auto",
        "scale": 1.0,
        "transform": "normal",
        "settle_timeout": 12.0,
        "settle_delay": 1.0,
        "reinitialize_on_start": True,
        "brightness_backend": "auto",
    },
    "input": {"rotate_touch_with_display": True, "ignore_touch_mouse_emulation": True, "disable_touchpad_in_kiosk": False},
    "audio": {"provider": "auto"},
    "temperature": {"primary": "auto"},
    "monitoring": {
        "thresholds": {
            "cpu_percent": 90,
            "memory_percent": 90,
            "disk_percent": 90,
            "temperature_c": 80,
        },
    },
    "idle": {
        "enabled": False,
        "dim_after_seconds": 300,
        "off_after_seconds": 600,
        "dim_brightness": 20,
        "wake_on_input": True,
    },
    "screensaver": {
        "enabled": False,
        "after_seconds": 120,
        "interval_seconds": 10,
        "fit": "contain",
        "shuffle": False,
        "background": "#000000",
        "keep_display_on": True,
        "image_dir": "/var/lib/kioskctl/screensaver",
    },
    "mqtt": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 1883,
        "username": "",
        "password": "",
        "base_topic": "kioskctl",
    },
    "plugins": {
        "homeassistant": {
            "enabled": False,
            "discovery_prefix": "homeassistant",
        },
        "digital_signage": {
            "installed": False,
            "enabled": False,
            "after_seconds": 120,
            "interval_seconds": 10,
            "fit": "cover",
            "shuffle": False,
            "background": "#000000",
            "keep_display_on": True,
            "schedule_enabled": False,
            "schedule_start": "00:00",
            "schedule_end": "23:59",
            "schedule_days": [0, 1, 2, 3, 4, 5, 6],
            "asset_dir": "/var/lib/kioskctl/plugins/digital-signage/assets",
        },
        "immich": {
            "installed": False,
            "enabled": False,
            "server_url": "",
            "api_key": "",
            "album_id": "",
            "after_seconds": 120,
            "interval_seconds": 15,
            "fit": "contain",
            "background": "#000000",
            "keep_display_on": True,
            "random_count": 100,
            "cache_seconds": 300,
        },
    },
    "update": {"command": ""},
}


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def validate_port(value: Any, name: str) -> int:
    """Return a validated TCP/UDP port number.

    Keep validation centralized so browser launch, the API server, MQTT and
    diagnostics all consume the same normalized values from load_config().
    """
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535, got {port}")
    return port


def _config_version(data: dict[str, Any]) -> int:
    # Configs predating an explicit schema version are treated as schema v1.
    raw = data.get("version", 1)
    try:
        version = int(raw or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Config version must be an integer, got {raw!r}") from exc
    if version < 1:
        raise ValueError(f"Config version must be >= 1, got {version}")
    if version > CURRENT_CONFIG_VERSION:
        raise ValueError(
            f"Config version {version} is newer than this kioskctl build supports "
            f"(max {CURRENT_CONFIG_VERSION})"
        )
    return version


def migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    """Explicitly migrate legacy config dictionaries to the current schema.

    v1/v2 -> v3 added browser/display/audio defaults. v3 -> v4 introduces
    the plugin section and moves Home Assistant-specific MQTT discovery
    settings out of the generic MQTT transport. v4 -> v5 adds browser touch
    experience settings (pages/zoom/pull-to-refresh) and idle/wake policy.
    v5 -> v6 adds the local slideshow screensaver configuration. v6 -> v7
    adds explicit screensaver/display-power coordination so a slideshow can
    keep the panel awake instead of being immediately hidden by the idle
    screen-off policy. v7 -> v8 adds touchscreen compatibility-pointer suppression
    so touch digitizers do not leave a compositor cursor parked onscreen. v8 -> v9 adds optional touchpad suppression while kiosk mode is active. v9 -> v10 adds the bundled plugin catalog and optional Digital Signage / Immich screensaver plugins while keeping the simple local screensaver in core. Legacy keys are translated so in-place upgrades
    preserve working state.
    """
    version = _config_version(data)
    migrated = copy.deepcopy(data)
    if version in (1, 2):
        migrated["version"] = 3
        version = 3
    if version == 3:
        mqtt_cfg = migrated.setdefault("mqtt", {})
        plugins = migrated.setdefault("plugins", {})
        ha = plugins.setdefault("homeassistant", {})
        if "enabled" not in ha:
            ha["enabled"] = bool(mqtt_cfg.get("home_assistant_discovery", False))
        if "discovery_prefix" not in ha:
            ha["discovery_prefix"] = str(mqtt_cfg.get("discovery_prefix", "homeassistant"))
        mqtt_cfg.pop("home_assistant_discovery", None)
        mqtt_cfg.pop("discovery_prefix", None)
        migrated["version"] = 4
        version = 4
    if version == 4:
        # The new v5 sections are merged from DEFAULT_CONFIG after migration.
        # Explicitly bump the schema so future incompatible changes can be
        # rejected instead of silently rewriting a configuration.
        migrated["version"] = 5
        version = 5
    if version == 5:
        # v6 adds the local slideshow screensaver. Defaults are merged below,
        # so no legacy keys need translation.
        migrated["version"] = 6
        version = 6
    if version == 6:
        # v7 adds screensaver.keep_display_on. The default is merged below.
        migrated["version"] = 7
        version = 7
    if version == 7:
        # v8 adds input.ignore_touch_mouse_emulation. The default is merged below.
        migrated["version"] = 8
        version = 8
    if version == 8:
        # v9 adds input.disable_touchpad_in_kiosk. The default is merged below.
        migrated["version"] = 9
        version = 9
    if version == 9:
        # v10 adds optional plugin catalog state for Digital Signage and Immich.
        # Defaults are merged below; existing simple screensaver settings stay core.
        migrated["version"] = 10
        version = 10
    if version != CURRENT_CONFIG_VERSION:
        raise ValueError(f"No migration path for config version {version}")
    return migrated


def _validate_config(cfg: dict[str, Any]) -> dict[str, Any]:
    cfg["browser"]["devtools_port"] = validate_port(
        cfg["browser"].get("devtools_port", 9222), "browser.devtools_port"
    )
    cfg["admin"]["port"] = validate_port(cfg["admin"].get("port", 2324), "admin.port")
    cfg["mqtt"]["port"] = validate_port(cfg["mqtt"].get("port", 1883), "mqtt.port")

    notification_mode = str(cfg["browser"].get("prompts", {}).get("notifications", "block")).lower()
    if notification_mode not in {"allow", "block", "ask"}:
        raise ValueError(
            "browser.prompts.notifications must be one of: allow, block, ask"
        )
    cfg["browser"]["prompts"]["notifications"] = notification_mode

    browser = cfg.setdefault("browser", {})
    try:
        zoom = float(browser.get("zoom", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("browser.zoom must be a number") from exc
    if not 0.5 <= zoom <= 2.0:
        raise ValueError("browser.zoom must be between 0.5 and 2.0")
    browser["zoom"] = round(zoom, 2)

    color_scheme = str(browser.get("color_scheme", "auto") or "auto").lower()
    if color_scheme not in {"auto", "light", "dark"}:
        raise ValueError("browser.color_scheme must be one of: auto, light, dark")
    browser["color_scheme"] = color_scheme

    pages = browser.get("pages", [])
    if pages is None:
        pages = []
    if not isinstance(pages, list):
        raise ValueError("browser.pages must be a list")
    normalized_pages: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for index, item in enumerate(pages):
        if not isinstance(item, dict):
            raise ValueError(f"browser.pages[{index}] must be a mapping")
        name = str(item.get("name", "")).strip() or f"Page {index + 1}"
        url = str(item.get("url", "")).strip()
        if not url.startswith(("http://", "https://", "file://")):
            raise ValueError(f"browser.pages[{index}].url must begin with http://, https://, or file://")
        key = name.casefold()
        if key in seen_names:
            raise ValueError(f"browser.pages contains duplicate name: {name}")
        seen_names.add(key)
        normalized_pages.append({"name": name[:80], "url": url})
    browser["pages"] = normalized_pages

    touch_ui = browser.setdefault("touch_ui", {})
    touch_ui["pull_to_refresh"] = bool(touch_ui.get("pull_to_refresh", True))
    try:
        threshold = int(touch_ui.get("pull_threshold_px", 110))
    except (TypeError, ValueError) as exc:
        raise ValueError("browser.touch_ui.pull_threshold_px must be an integer") from exc
    if not 60 <= threshold <= 240:
        raise ValueError("browser.touch_ui.pull_threshold_px must be between 60 and 240")
    touch_ui["pull_threshold_px"] = threshold
    touch_ui["edge_drawer"] = bool(touch_ui.get("edge_drawer", False))
    touch_ui["onscreen_keyboard"] = bool(touch_ui.get("onscreen_keyboard", False))

    monitoring = cfg.setdefault("monitoring", {}).setdefault("thresholds", {})
    threshold_limits = {
        "cpu_percent": (0, 100, 90),
        "memory_percent": (0, 100, 90),
        "disk_percent": (0, 100, 90),
        "temperature_c": (0, 150, 80),
    }
    for key, (minimum, maximum, default) in threshold_limits.items():
        try:
            value = int(monitoring.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"monitoring.thresholds.{key} must be an integer") from exc
        if not minimum <= value <= maximum:
            raise ValueError(
                f"monitoring.thresholds.{key} must be between {minimum} and {maximum}"
            )
        monitoring[key] = value

    idle = cfg.setdefault("idle", {})
    idle["enabled"] = bool(idle.get("enabled", False))
    idle["wake_on_input"] = bool(idle.get("wake_on_input", True))
    for key, default in (("dim_after_seconds", 300), ("off_after_seconds", 600), ("dim_brightness", 20)):
        try:
            idle[key] = int(idle.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"idle.{key} must be an integer") from exc
    if idle["dim_after_seconds"] < 0 or idle["off_after_seconds"] < 0:
        raise ValueError("idle dim/off timeouts cannot be negative")
    if idle["off_after_seconds"] and idle["dim_after_seconds"] and idle["off_after_seconds"] <= idle["dim_after_seconds"]:
        raise ValueError("idle.off_after_seconds must be greater than idle.dim_after_seconds")
    if not 1 <= idle["dim_brightness"] <= 100:
        raise ValueError("idle.dim_brightness must be between 1 and 100")

    input_cfg = cfg.setdefault("input", {})
    input_cfg["rotate_touch_with_display"] = bool(input_cfg.get("rotate_touch_with_display", True))
    input_cfg["ignore_touch_mouse_emulation"] = bool(input_cfg.get("ignore_touch_mouse_emulation", True))
    input_cfg["disable_touchpad_in_kiosk"] = bool(input_cfg.get("disable_touchpad_in_kiosk", False))

    screensaver = cfg.setdefault("screensaver", {})
    screensaver["enabled"] = bool(screensaver.get("enabled", False))
    screensaver["shuffle"] = bool(screensaver.get("shuffle", False))
    screensaver["keep_display_on"] = bool(screensaver.get("keep_display_on", True))
    for key, default in (("after_seconds", 120), ("interval_seconds", 10)):
        try:
            screensaver[key] = int(screensaver.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"screensaver.{key} must be an integer") from exc
    if screensaver["after_seconds"] < 5:
        raise ValueError("screensaver.after_seconds must be at least 5")
    if not 2 <= screensaver["interval_seconds"] <= 3600:
        raise ValueError("screensaver.interval_seconds must be between 2 and 3600")
    fit = str(screensaver.get("fit", "contain") or "contain").lower()
    if fit not in {"contain", "cover"}:
        raise ValueError("screensaver.fit must be contain or cover")
    screensaver["fit"] = fit
    background = str(screensaver.get("background", "#000000") or "#000000").strip()
    if not (len(background) == 7 and background.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in background[1:])):
        raise ValueError("screensaver.background must be a #RRGGBB color")
    screensaver["background"] = background
    image_dir = str(screensaver.get("image_dir", "/var/lib/kioskctl/screensaver") or "/var/lib/kioskctl/screensaver")
    screensaver["image_dir"] = image_dir

    cfg["version"] = CURRENT_CONFIG_VERSION
    return cfg



def merge_preserved_integrations(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """Return *current* with only integration configuration copied from *previous*.

    This is intentionally narrow: a development ``--fresh`` install may keep
    MQTT credentials and plugin settings without carrying browser/session/UI
    state forward. Both inputs are copied so callers cannot accidentally mutate
    a live configuration while preparing the replacement.
    """
    out = copy.deepcopy(current)
    old = copy.deepcopy(previous)
    if isinstance(old.get("mqtt"), dict):
        out["mqtt"] = old["mqtt"]
    if isinstance(old.get("plugins"), dict):
        out["plugins"] = old["plugins"]
    return out


def load_config(path: Path | str = DEFAULT_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return _validate_config(copy.deepcopy(DEFAULT_CONFIG))
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    migrated = migrate_config(data)
    cfg = _merge(DEFAULT_CONFIG, migrated)
    return _validate_config(cfg)


def save_config(cfg: dict[str, Any], path: Path | str = DEFAULT_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.stat() if path.exists() else None
    tmp = path.with_suffix(path.suffix + ".tmp")
    validated = _validate_config(migrate_config(cfg))
    tmp.write_text(yaml.safe_dump(validated, sort_keys=False))
    if previous is not None:
        # The agent normally writes as root while the graphical kiosk user must
        # still be able to read the file. Preserve the installer's root:kioskctl
        # ownership and 0640 mode across Web/API configuration changes.
        os.chown(tmp, previous.st_uid, previous.st_gid)
        os.chmod(tmp, previous.st_mode & 0o777)
    else:
        os.chmod(tmp, 0o600)
    tmp.replace(path)
