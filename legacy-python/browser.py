from __future__ import annotations

import base64
import json
import os
import pwd
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from websocket import create_connection

from .config import validate_port

_RUNTIME_SCRIPT_IDS: dict[int, str] = {}


def kiosk_home(cfg: dict[str, Any]) -> Path:
    user = str(cfg.get("system", {}).get("kiosk_user", "kioskctl"))
    try:
        return Path(pwd.getpwnam(user).pw_dir)
    except KeyError:
        return Path(f"/home/{user}")


def browser_provider(cfg: dict[str, Any]) -> str:
    configured = str(cfg.get("browser", {}).get("provider", "auto"))
    if configured and configured != "auto":
        return configured
    executable = chromium_executable(str(cfg.get("browser", {}).get("executable", "auto")))
    if executable.startswith("/snap/") or executable == "/snap/bin/chromium":
        return "chromium-snap"
    if "google-chrome" in executable:
        return "chrome-native"
    return "chromium-native"


def chromium_executable(configured: str = "auto") -> str:
    if configured and configured != "auto":
        return configured
    explicit = [
        "/snap/bin/chromium",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
    ]
    for candidate in explicit:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    for candidate in ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome"):
        found = shutil.which(candidate)
        if found:
            return found
    raise FileNotFoundError("No supported Chromium/Chrome executable found")


def browser_version(executable: str) -> str | None:
    try:
        p = subprocess.run([executable, "--version"], text=True, capture_output=True, timeout=5, check=False)
        return (p.stdout or p.stderr).strip() or None
    except Exception:
        return None


def resolved_user_data_dir(cfg: dict[str, Any]) -> Path:
    configured = str(cfg.get("browser", {}).get("user_data_dir", "auto"))
    if configured and configured != "auto":
        return Path(configured)
    home = kiosk_home(cfg)
    provider = browser_provider(cfg)
    if provider == "chromium-snap":
        return home / "snap/chromium/common/kioskctl-profile"
    return home / ".local/share/kioskctl/chromium"


def _deep_update(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_update(out[key], value)
        else:
            out[key] = value
    return out


def managed_policy(cfg: dict[str, Any]) -> dict[str, Any]:
    prompts = cfg.get("browser", {}).get("prompts", {})
    notification_mode = str(prompts.get("notifications", "block")).lower()
    # Chromium managed policy enum: 1=allow, 2=block, 3=ask.
    notification_setting = {"allow": 1, "block": 2, "ask": 3}.get(notification_mode, 2)
    return {
        "PasswordManagerEnabled": bool(prompts.get("password_manager", False)),
        "AutofillAddressEnabled": bool(prompts.get("autofill", False)),
        "AutofillCreditCardEnabled": bool(prompts.get("autofill", False)),
        "DefaultNotificationsSetting": notification_setting,
        "TranslateEnabled": bool(prompts.get("translate", False)),
    }


def managed_policy_path(cfg: dict[str, Any]) -> Path | None:
    provider = browser_provider(cfg)
    if provider == "chromium-snap":
        return None
    if provider == "chrome-native":
        return Path("/etc/opt/chrome/policies/managed/kioskctl.json")
    return Path("/etc/chromium/policies/managed/kioskctl.json")


def write_managed_policy(cfg: dict[str, Any]) -> str | None:
    """Write native Chromium/Chrome enterprise policy when running as root.

    Snap Chromium is kept on profile preferences/flags because its confinement
    and policy paths vary by release.  Native Chromium on Debian/Arch/Fedora
    consistently honors the /etc/chromium managed-policy tree.
    """
    path = managed_policy_path(cfg)
    if path is None or os.geteuid() != 0:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(managed_policy(cfg), indent=2, sort_keys=True) + "\n")
    os.chmod(path, 0o644)
    return str(path)


def prepare_browser_profile(cfg: dict[str, Any]) -> Path:
    """Create/update kiosk-safe Chromium profile preferences.

    We prefer profile preferences here because they work for both native Chromium
    and Canonical's strictly-confined Chromium Snap. Native installations may
    later add machine-level managed policy as an additional layer.
    """
    profile = resolved_user_data_dir(cfg)
    default_dir = profile / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = default_dir / "Preferences"
    try:
        current = json.loads(prefs_path.read_text()) if prefs_path.exists() else {}
        if not isinstance(current, dict):
            current = {}
    except Exception:
        current = {}

    prompts = cfg.get("browser", {}).get("prompts", {})
    notification_mode = str(prompts.get("notifications", "block")).lower()
    # Chromium profile preference enum differs from policy: 0=ask, 1=allow, 2=block.
    notification_setting = {"allow": 1, "block": 2, "ask": 0}.get(notification_mode, 2)
    wanted = {
        "credentials_enable_service": bool(prompts.get("password_manager", False)),
        "profile": {
            "password_manager_enabled": bool(prompts.get("password_manager", False)),
            "password_manager_leak_detection": False,
            "default_content_setting_values": {"notifications": notification_setting},
        },
        "autofill": {
            "profile_enabled": bool(prompts.get("autofill", False)),
            "credit_card_enabled": bool(prompts.get("autofill", False)),
        },
        "translate": {"enabled": bool(prompts.get("translate", False))},
        "browser": {"check_default_browser": False, "has_seen_welcome_page": True},
        "distribution": {"skip_first_run_ui": True},
    }
    prefs_path.write_text(json.dumps(_deep_update(current, wanted), indent=2, sort_keys=True))
    return profile


def build_browser_command(cfg: dict[str, Any]) -> list[str]:
    b = cfg["browser"]
    executable = chromium_executable(str(b.get("executable", "auto")))
    profile = prepare_browser_profile(cfg)
    prompts = b.get("prompts", {})
    disabled_features = ["MediaRouter"]
    if not prompts.get("translate", False):
        disabled_features.append("Translate")
    if not prompts.get("autofill", False):
        disabled_features += ["AutofillServerCommunication", "AutofillEnablePayments"]
    devtools_port = validate_port(b.get("devtools_port", 9222), "browser.devtools_port")
    enabled_features = ["UseOzonePlatform"]
    color_scheme = str(b.get("color_scheme", "auto") or "auto").lower()
    if color_scheme == "dark":
        # DevTools media emulation is useful for standards-aware sites, but a
        # kiosk-wide dark choice should also survive navigation and affect sites
        # that never consult prefers-color-scheme. Chromium's command-line
        # forced-dark path is persistent for the life of the browser process.
        enabled_features.append("WebContentsForceDark")

    args = [
        executable,
        "--kiosk",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-infobars",
        "--disable-prompt-on-repost",
        "--password-store=basic",
        f"--disable-features={','.join(disabled_features)}",
        "--ozone-platform=wayland",
        f"--enable-features={','.join(enabled_features)}",
        f"--user-data-dir={profile}",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={devtools_port}",
        f"--remote-allow-origins=http://127.0.0.1:{devtools_port}",
    ]
    if not prompts.get("password_manager", False):
        args.append("--disable-save-password-bubble")
    if str(prompts.get("notifications", "block")).lower() == "block":
        args.append("--disable-notifications")
    if color_scheme == "dark":
        args.append("--force-dark-mode")
    if b.get("incognito"):
        args.append("--incognito")
    args.extend(str(x) for x in b.get("extra_args", []))
    args.append(str(b["url"]))
    return args


class DevTools:
    def __init__(self, port: int = 9222, preferred_url: str | None = None):
        self.port = validate_port(port, "browser.devtools_port")
        self.preferred_url = str(preferred_url or "")

    def _targets(self) -> list[dict[str, Any]]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=2) as r:
            return json.loads(r.read().decode())

    def version(self) -> dict[str, Any]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=2) as r:
            return json.loads(r.read().decode())

    def available(self) -> bool:
        try:
            self.version()
            return True
        except Exception:
            return False

    @staticmethod
    def _is_external_page(target: dict[str, Any]) -> bool:
        if target.get("type") != "page":
            return False
        url = str(target.get("url", "") or "")
        return url.startswith(("http://", "https://", "file://"))

    def _page(self) -> dict[str, Any]:
        """Return the real kiosk content target, not Chromium's own WebUI.

        Chromium 153 can expose a top-chrome WebUI page before the kiosk tab in
        /json/list.  Older kioskctl builds blindly selected pages[0], which can
        make current_url empty/unknown and inject touch helpers into the wrong
        document.  Prefer normal web/file pages, then favor the configured kiosk
        URL when more than one external page exists.
        """
        targets = self._targets()
        pages = [x for x in targets if x.get("type") == "page"]
        if not pages:
            raise RuntimeError("No Chromium page target is available")

        external = [x for x in pages if self._is_external_page(x)]
        candidates = external or pages
        preferred = self.preferred_url
        if preferred:
            # Exact/current-descendant matches first.  This still follows the
            # same tab after a SPA route change or configured sub-page navigate.
            for target in candidates:
                url = str(target.get("url", "") or "")
                if url == preferred or url.startswith(preferred.rstrip("/") + "/"):
                    return target
            try:
                from urllib.parse import urlsplit
                wanted = urlsplit(preferred)
                if wanted.scheme and wanted.netloc:
                    for target in candidates:
                        got = urlsplit(str(target.get("url", "") or ""))
                        if got.scheme == wanted.scheme and got.netloc == wanted.netloc:
                            return target
            except Exception:
                pass
        return candidates[0]

    def target_info(self) -> dict[str, Any]:
        target = self._page()
        return {
            "id": target.get("id"),
            "title": target.get("title"),
            "url": target.get("url"),
            "type": target.get("type"),
        }

    def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        target = self._page()
        ws = create_connection(target["webSocketDebuggerUrl"], timeout=3, origin=f"http://127.0.0.1:{self.port}")
        try:
            msg_id = int(time.time() * 1000) % 2_000_000_000
            ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            while True:
                response = json.loads(ws.recv())
                if response.get("id") == msg_id:
                    if "error" in response:
                        raise RuntimeError(response["error"].get("message", "DevTools error"))
                    return response.get("result", {})
        finally:
            ws.close()

    def bring_to_front(self) -> None:
        self._call("Page.bringToFront")

    def reload(self) -> None:
        self.bring_to_front()
        self._call("Page.reload", {"ignoreCache": True})

    def navigate(self, url: str) -> None:
        self.bring_to_front()
        self._call("Page.navigate", {"url": url})

    def replace(self, url: str) -> None:
        """Navigate without leaving the temporary destination in browser history.

        Screensaver entry/exit uses this so a later user back gesture does not
        unexpectedly return to the local slideshow page.
        """
        self.bring_to_front()
        encoded = json.dumps(str(url))
        self._call("Runtime.evaluate", {"expression": f"location.replace({encoded})"})

    def back(self) -> None:
        self.bring_to_front()
        self._call("Runtime.evaluate", {"expression": "history.back()"})

    def screenshot_png(self) -> bytes:
        self._call("Page.enable")
        result = self._call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        return base64.b64decode(result["data"])

    def current_url(self) -> str:
        return str(self._page().get("url", ""))

    def set_color_scheme(self, scheme: str) -> str:
        """Apply the requested light/dark preference to the physical kiosk page.

        ``prefers-color-scheme`` is enough for sites that opt in to dark mode,
        but many public sites still render a light palette. Newer Chromium
        builds expose ``Emulation.setAutoDarkModeOverride`` which force-renders
        those pages in dark mode. Use both mechanisms when available and fall
        back to media emulation on older Chromium releases.
        """
        value = str(scheme or "auto").lower()
        if value not in {"auto", "light", "dark"}:
            raise ValueError("color scheme must be auto, light, or dark")

        # Always publish the CSS preference first. This is the standards-based
        # signal used by Home Assistant and other applications with native dark
        # themes.
        features = [] if value == "auto" else [{"name": "prefers-color-scheme", "value": value}]
        self._call("Emulation.setEmulatedMedia", {"media": "", "features": features})

        # Chromium 153 supports this experimental CDP command. It applies an
        # automatic dark transform even to sites that ignore
        # prefers-color-scheme (Google's public page is a useful example). Keep
        # it best-effort so older distro Chromium packages remain supported.
        try:
            if value == "dark":
                self._call("Emulation.setAutoDarkModeOverride", {"enabled": True})
            elif value == "light":
                self._call("Emulation.setAutoDarkModeOverride", {"enabled": False})
            else:
                # Omitting enabled clears an existing override and returns
                # Chromium to its normal automatic/system behavior.
                self._call("Emulation.setAutoDarkModeOverride", {})
        except Exception:
            pass
        return value

    def viewport_details(self) -> dict[str, float]:
        result = self._call("Runtime.evaluate", {
            "expression": "({innerWidth:window.innerWidth,innerHeight:window.innerHeight,outerWidth:window.outerWidth,outerHeight:window.outerHeight,dpr:window.devicePixelRatio,screenWidth:screen.width,screenHeight:screen.height})",
            "returnByValue": True,
        })
        value = result.get("result", {}).get("value", {})
        return {k: float(value.get(k, 0) or 0) for k in ("innerWidth", "innerHeight", "outerWidth", "outerHeight", "dpr", "screenWidth", "screenHeight")}

    def viewport(self) -> tuple[float, float]:
        value = self.viewport_details()
        return max(value["innerWidth"], 1), max(value["innerHeight"], 1)

    def focus_info(self) -> dict[str, Any]:
        expression = r"""
(() => {
  const el = document.activeElement;
  if (!el) return {editable:false, tag:null};
  const tag = (el.tagName || '').toLowerCase();
  const type = (el.type || '').toLowerCase();
  const nonText = ['button','checkbox','color','file','hidden','image','radio','range','reset','submit'];
  const editable = el.isContentEditable || tag === 'textarea' || (tag === 'input' && !nonText.includes(type));
  return {editable, tag, type, id:el.id || '', name:el.name || '', contentEditable:!!el.isContentEditable};
})()
"""
        result = self._call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return result.get("result", {}).get("value", {}) or {"editable": False}

    def click_normalized(self, x: float, y: float) -> dict[str, Any]:
        self.bring_to_front()
        width, height = self.viewport()
        px = max(0.0, min(1.0, x)) * width
        py = max(0.0, min(1.0, y)) * height
        self._call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": px, "y": py, "button": "left", "clickCount": 1})
        self._call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": px, "y": py, "button": "left", "clickCount": 1})
        time.sleep(0.05)
        return self.focus_info()

    def hide_runtime_keyboard(self) -> bool:
        """Hide kioskctl's in-page keyboard without disturbing page focus."""
        try:
            result = self._call("Runtime.evaluate", {
                "expression": "(() => { const r=window.__kioskctlRuntime; if(r&&typeof r.hideKeyboard==='function'){r.hideKeyboard();return true;} const k=document.getElementById('kioskctl-keyboard'); if(k){k.classList.remove('open');return true;} return false; })()",
                "returnByValue": True,
            })
            return bool(result.get("result", {}).get("value", False))
        except Exception:
            return False

    def insert_text(self, text: str) -> dict[str, Any]:
        self.bring_to_front()
        # Remote administration already provides its own keyboard/text box. Keep
        # the physical kiosk keyboard out of the way while remote text is sent.
        self.hide_runtime_keyboard()
        focus_before = self.focus_info()
        method = "insertText"
        # Input.insertText is ideal when the top document can prove an editable
        # target. For cross-origin iframes and canvas-heavy applications the top
        # document often only reports the iframe itself; CDP key events still go
        # to Chromium's real focused renderer, so use char events as a fallback.
        if focus_before.get("editable", False):
            self._call("Input.insertText", {"text": text})
        else:
            method = "keyEvents"
            for char in text:
                self._call("Input.dispatchKeyEvent", {"type": "char", "text": char, "unmodifiedText": char})
        time.sleep(0.03)
        focus_after = self.focus_info()
        return {"before": focus_before, "after": focus_after, "method": method}

    def key(self, key: str) -> None:
        # Chromium does not reliably act on key names alone. In particular,
        # Enter and Backspace regressed when we sent only {key: ...}. Send the
        # DOM code plus the platform virtual-key code so normal form submit,
        # text deletion, focus traversal and navigation keys behave like a
        # physical keyboard.
        specs: dict[str, dict[str, Any]] = {
            "Enter": {"code": "Enter", "vk": 13, "text": "\r"},
            "Escape": {"code": "Escape", "vk": 27},
            "Backspace": {"code": "Backspace", "vk": 8, "commands": ["deleteBackward"]},
            "Tab": {"code": "Tab", "vk": 9},
            "ArrowUp": {"code": "ArrowUp", "vk": 38},
            "ArrowDown": {"code": "ArrowDown", "vk": 40},
            "ArrowLeft": {"code": "ArrowLeft", "vk": 37},
            "ArrowRight": {"code": "ArrowRight", "vk": 39},
            "Home": {"code": "Home", "vk": 36},
            "End": {"code": "End", "vk": 35},
            "PageUp": {"code": "PageUp", "vk": 33},
            "PageDown": {"code": "PageDown", "vk": 34},
        }
        spec = specs.get(key)
        if spec is None:
            raise ValueError(f"Unsupported remote key: {key}")
        self.bring_to_front()
        self.hide_runtime_keyboard()
        base = {
            "key": key,
            "code": str(spec["code"]),
            "windowsVirtualKeyCode": int(spec["vk"]),
            "nativeVirtualKeyCode": int(spec["vk"]),
        }
        down = dict(base)
        # rawKeyDown is the most reliable path for editing/navigation keys.
        # Enter needs text on keyDown so forms receive the same event sequence
        # as a real Enter key.
        if "text" in spec:
            down.update({"type": "keyDown", "text": str(spec["text"]), "unmodifiedText": str(spec["text"])})
        else:
            down["type"] = "rawKeyDown"
        if "commands" in spec:
            down["commands"] = list(spec["commands"])
        self._call("Input.dispatchKeyEvent", down)
        up = dict(base)
        up["type"] = "keyUp"
        self._call("Input.dispatchKeyEvent", up)

    def notify_geometry_change(self) -> None:
        """Nudge the page after a Wayland output reprobe/modeset."""
        try:
            self._call("Emulation.clearDeviceMetricsOverride")
        except Exception:
            pass
        try:
            self._call("Runtime.evaluate", {"expression": "window.dispatchEvent(new Event('resize')); true", "returnByValue": True})
        except Exception:
            pass


def _systemd() -> bool:
    return bool(shutil.which("systemctl") and Path("/run/systemd/system").exists())


def restart_service(name: str) -> None:
    if _systemd():
        subprocess.run(["systemctl", "restart", name], check=True, timeout=20)
        return
    if shutil.which("rc-service"):
        n = name[:-8] if name.endswith(".service") else name
        subprocess.run(["rc-service", n, "restart"], check=True, timeout=20)
        return
    raise RuntimeError("No supported service manager found")


def service_active(name: str) -> bool:
    if _systemd():
        p = subprocess.run(["systemctl", "is-active", "--quiet", name], check=False, timeout=5)
        return p.returncode == 0
    if shutil.which("rc-service"):
        n = name[:-8] if name.endswith(".service") else name
        p = subprocess.run(["rc-service", n, "status"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        return p.returncode == 0
    return False


def browser_runtime_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return the browser-side feature configuration exposed to injected UI.

    Keep this deliberately small: the page never receives API tokens, MQTT
    credentials, or any other management-plane secret.
    """
    browser = cfg.get("browser", {})
    touch = browser.get("touch_ui", {})
    pages = [
        {"name": str(item.get("name", "Page")), "url": str(item.get("url", ""))}
        for item in browser.get("pages", [])
        if isinstance(item, dict) and item.get("url")
    ]
    return {
        "home_url": str(browser.get("url", "https://example.com")),
        "pages": pages,
        "zoom": float(browser.get("zoom", 1.0) or 1.0),
        "color_scheme": str(browser.get("color_scheme", "auto") or "auto"),
        "pull_to_refresh": bool(touch.get("pull_to_refresh", True)),
        "pull_threshold_px": int(touch.get("pull_threshold_px", 110) or 110),
        "edge_drawer": bool(touch.get("edge_drawer", False)),
        "onscreen_keyboard": bool(touch.get("onscreen_keyboard", False)),
    }


def browser_runtime_script(cfg: dict[str, Any]) -> str:
    """Build the self-contained script injected into every kiosk document.

    Features are intentionally implemented in-page rather than through a
    browser extension so they work with native Chromium and Ubuntu's Snap.
    The script cleans up a previous kioskctl injection before installing a new
    one, which makes repeated configuration/reload cycles safe.
    """
    feature_json = json.dumps(browser_runtime_config(cfg), separators=(",", ":"))
    return r'''(() => {
  const CONFIG = __CONFIG__;
  const KEY = '__kioskctlRuntime';
  // Local screensaver/signage surfaces are already full-screen kiosk UI. Do
  // not place the browser drawer/keyboard/pull indicator on top of them.
  if ((location.hostname === '127.0.0.1' || location.hostname === 'localhost') &&
      (location.pathname === '/screensaver' || location.pathname.startsWith('/plugin/digital-signage/') || location.pathname.startsWith('/plugin/immich/'))) return;

  function boot() {
    if (!document.documentElement || !document.body) {
      requestAnimationFrame(boot);
      return;
    }

    try {
      const previous = window[KEY];
      if (previous && typeof previous.cleanup === 'function') previous.cleanup();
    } catch (_) {}

    const cleanup = [];
    const state = { cleanup: () => cleanup.splice(0).reverse().forEach(fn => { try { fn(); } catch (_) {} }) };
    window[KEY] = state;

    const add = (target, type, handler, options) => {
      target.addEventListener(type, handler, options);
      cleanup.push(() => target.removeEventListener(type, handler, options));
    };
    const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
    const isKioskUi = (target) => !!(target && target.closest && target.closest('[data-kioskctl-ui]'));

    const style = document.createElement('style');
    style.id = 'kioskctl-runtime-style';
    style.dataset.kioskctlUi = '1';
    style.textContent = `
      #kioskctl-pull-indicator{position:fixed;left:50%;top:0;transform:translate(-50%,-58px);z-index:2147483646;
        height:44px;min-width:150px;padding:0 18px;border-radius:0 0 14px 14px;background:rgba(10,17,26,.94);color:#eef7ff;
        display:flex;align-items:center;justify-content:center;gap:8px;font:600 14px/1 system-ui,sans-serif;box-shadow:0 7px 24px rgba(0,0,0,.32);
        transition:transform .16s ease,background .16s ease;pointer-events:none;backdrop-filter:blur(8px)}
      #kioskctl-edge-tab{position:fixed;right:0;top:44%;z-index:2147483645;width:24px;height:72px;border:0;border-radius:13px 0 0 13px;
        background:rgba(15,24,35,.82);color:#fff;font:700 16px system-ui;box-shadow:0 4px 18px rgba(0,0,0,.3);touch-action:manipulation}
      #kioskctl-edge-panel{position:fixed;right:0;top:0;bottom:0;z-index:2147483646;width:min(260px,78vw);padding:22px 16px;
        background:rgba(12,18,27,.97);color:#f2f6fa;box-shadow:-12px 0 32px rgba(0,0,0,.35);transform:translateX(105%);transition:transform .18s ease;
        font:500 14px system-ui,sans-serif;overflow:auto;backdrop-filter:blur(12px);display:flex;flex-direction:column}
      #kioskctl-edge-panel.open{transform:translateX(0)}
      #kioskctl-edge-panel h3{margin:0 0 14px;font-size:17px} #kioskctl-edge-panel .krow{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0}
      #kioskctl-edge-panel button,#kioskctl-keyboard button{border:1px solid rgba(255,255,255,.12);background:#1e2b3b;color:#f5f8fb;border-radius:9px;
        padding:11px 10px;font:650 14px system-ui,sans-serif;touch-action:manipulation} #kioskctl-edge-panel button:active,#kioskctl-keyboard button:active{background:#35516e}
      #kioskctl-edge-panel .kpages{display:grid;gap:7px;margin-top:12px} #kioskctl-edge-panel .kpage{width:100%;text-align:left}
      #kioskctl-edge-panel .kclose{margin-top:auto;width:100%;background:#b52d38;border-color:#d85a64;color:#fff}
      #kioskctl-edge-panel .kclose:active{background:#8e2029}
      #kioskctl-keyboard{position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:rgba(10,15,23,.98);padding:8px 8px 12px;
        box-shadow:0 -12px 30px rgba(0,0,0,.38);transform:translateY(105%);transition:transform .16s ease;touch-action:manipulation;backdrop-filter:blur(12px)}
      #kioskctl-keyboard.open{transform:translateY(0)} #kioskctl-keyboard .kline{display:flex;justify-content:center;gap:5px;margin:5px 0}
      #kioskctl-keyboard button{min-width:7.2vw;max-width:72px;flex:1;padding:10px 5px} #kioskctl-keyboard button.wide{flex:1.7} #kioskctl-keyboard button.space{flex:4}
      html.kioskctl-cursor-hidden,html.kioskctl-cursor-hidden *{cursor:none!important}
    `;
    document.documentElement.appendChild(style);
    cleanup.push(() => style.remove());

    // A kiosk should not leave a mouse pointer parked over the dashboard.  A
    // one-shot timeout proved too easy to starve: Chromium can emit trusted
    // pointer/mouse movement while touch overlays, reloads, or navigation are
    // rearranging content underneath a stationary pointer. Track the last real
    // physical mouse coordinate change and use a watchdog that always wins.
    let touchSeenUntil = 0;
    let lastRealMouseAt = -1e9;
    let lastMouseX = null, lastMouseY = null;
    const hideCursor = () => document.documentElement.classList.add('kioskctl-cursor-hidden');
    const revealCursor = () => document.documentElement.classList.remove('kioskctl-cursor-hidden');
    const noteTouch = () => {
      touchSeenUntil = performance.now() + 3000;
      hideCursor();
    };
    const noteRealMouse = (event=null, allowClick=false) => {
      const pointerType = String(event?.pointerType || 'mouse');
      if (pointerType !== 'mouse' || performance.now() < touchSeenUntil || event?.sourceCapabilities?.firesTouchEvents) {
        hideCursor();
        return;
      }
      if (event && event.isTrusted === false) return;
      const x = Number(event?.screenX), y = Number(event?.screenY);
      const haveCoords = Number.isFinite(x) && Number.isFinite(y);
      const moved = haveCoords && (lastMouseX == null || lastMouseY == null || Math.abs(x-lastMouseX) > 1 || Math.abs(y-lastMouseY) > 1);
      if (haveCoords) { lastMouseX = x; lastMouseY = y; }
      // pointerdown from a real mouse is deliberate even if it did not move.
      if (!moved && !allowClick) return;
      lastRealMouseAt = performance.now();
      revealCursor();
    };
    add(window, 'touchstart', noteTouch, {capture:true, passive:true});
    add(document, 'pointermove', e => noteRealMouse(e, false), {capture:true, passive:true});
    add(document, 'pointerdown', e => {
      if (String(e.pointerType || '') === 'touch' || e.sourceCapabilities?.firesTouchEvents) noteTouch();
      else noteRealMouse(e, true);
    }, {capture:true, passive:true});
    // The watchdog prevents repeated synthetic layout-related pointer events from
    // keeping the pointer visible forever after pull-refresh or drawer navigation.
    const cursorWatchdog = setInterval(() => {
      if (performance.now() - lastRealMouseAt >= 1800) hideCursor();
    }, 250);
    hideCursor();
    cleanup.push(() => { clearInterval(cursorWatchdog); document.documentElement.classList.remove('kioskctl-cursor-hidden'); });

    let zoom = clamp(Number(CONFIG.zoom || 1), .5, 2);
    function applyZoom(value) {
      zoom = clamp(Math.round(Number(value) * 10) / 10, .5, 2);
      document.documentElement.style.zoom = String(zoom);
      state.zoom = zoom;
      const label = document.getElementById('kioskctl-zoom-label');
      if (label) label.textContent = `${Math.round(zoom * 100)}%`;
    }
    applyZoom(zoom);
    cleanup.push(() => { document.documentElement.style.zoom = ''; });

    // Pull down from the very top of the page to perform a hard reload.
    // Use Touch Events rather than Pointer Events for the gesture. Chromium may
    // issue pointercancel as soon as native scrolling takes ownership of a
    // touchscreen drag; a non-passive touchmove lets kioskctl claim a downward
    // gesture only after it has armed at the top of the current scroll area.
    if (CONFIG.pull_to_refresh) {
      const indicator = document.createElement('div');
      indicator.id = 'kioskctl-pull-indicator';
      indicator.dataset.kioskctlUi = '1';
      indicator.textContent = '↓ Pull to refresh';
      document.body.appendChild(indicator);
      cleanup.push(() => indicator.remove());
      const threshold = clamp(Number(CONFIG.pull_threshold_px || 110), 60, 240);
      let tracking = false, touchId = null, startX = 0, startY = 0, distance = 0;
      const oldOverscroll = document.documentElement.style.overscrollBehaviorY;
      document.documentElement.style.overscrollBehaviorY = 'contain';
      cleanup.push(() => { document.documentElement.style.overscrollBehaviorY = oldOverscroll; });

      const atTop = (target=null) => {
        let el = target && target.nodeType === 1 ? target : null;
        while (el && el !== document.body && el !== document.documentElement) {
          try {
            const cs = getComputedStyle(el);
            const oy = cs.overflowY;
            if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 2) return Number(el.scrollTop || 0) <= 1;
          } catch (_) {}
          el = el.parentElement || (el.getRootNode && el.getRootNode().host) || null;
        }
        return Math.max(
          Number(document.scrollingElement?.scrollTop || 0),
          Number(document.documentElement?.scrollTop || 0),
          Number(document.body?.scrollTop || 0)
        ) <= 1;
      };
      const reset = () => {
        tracking = false; touchId = null; distance = 0;
        indicator.textContent = '↓ Pull to refresh';
        indicator.style.transition = 'transform .16s ease,background .16s ease';
        indicator.style.transform = 'translate(-50%,-58px)';
        indicator.style.background = 'rgba(10,17,26,.94)';
      };
      const findTouch = list => {
        if (touchId == null) return list && list.length ? list[0] : null;
        for (const t of Array.from(list || [])) if (t.identifier === touchId) return t;
        return null;
      };
      const start = e => {
        if (isKioskUi(e.target) || !atTop(e.target) || !e.touches || e.touches.length !== 1) return;
        const t = e.touches[0];
        tracking = true; touchId = t.identifier; startX = t.clientX; startY = t.clientY; distance = 0;
      };
      const move = e => {
        if (!tracking) return;
        const t = findTouch(e.touches); if (!t) return;
        const dx = t.clientX - startX, dy = t.clientY - startY;
        if (dy < -10 || (Math.abs(dx) > Math.abs(dy) * .9 && Math.abs(dx) > 12)) { reset(); return; }
        if (dy <= 0) return;
        // Claim the downward gesture before Chromium/native scrolling can cancel
        // it. We intentionally do not re-check scrollTop mid-gesture because
        // doing so caused the indicator to disappear during a valid pull.
        if (dy > 3 && e.cancelable) e.preventDefault();
        distance = Math.min(dy, threshold * 1.55);
        const visible = Math.min(50, Math.max(0, distance * .44));
        indicator.style.transition = 'none';
        indicator.style.transform = `translate(-50%,${visible - 44}px)`;
        indicator.textContent = distance >= threshold ? '↻ Release to refresh' : '↓ Pull to refresh';
        indicator.style.background = distance >= threshold ? 'rgba(27,104,151,.96)' : 'rgba(10,17,26,.94)';
      };
      const finish = e => {
        if (!tracking) return;
        // If another finger is still active, keep tracking the original one.
        if (findTouch(e.touches)) return;
        const refresh = distance >= threshold;
        indicator.style.transition = 'transform .16s ease,background .16s ease';
        tracking = false; touchId = null;
        if (refresh) {
          indicator.textContent = '↻ Refreshing…';
          indicator.style.transform = 'translate(-50%,0)';
          noteTouch();
          setTimeout(() => location.reload(), 90);
        } else reset();
      };
      add(window, 'touchstart', start, {capture:true, passive:true});
      add(window, 'touchmove', move, {capture:true, passive:false});
      add(window, 'touchend', finish, {capture:true, passive:true});
      add(window, 'touchcancel', reset, {capture:true, passive:true});
    }

    let keyboard = null;
    let lastEditable = null;
    const deepActive = () => {
      let el = document.activeElement;
      while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
      return el;
    };
    const isEditable = (el) => {
      if (!el) return false;
      const tag = String(el.tagName || '').toLowerCase();
      const type = String(el.type || '').toLowerCase();
      return !!el.isContentEditable || tag === 'textarea' || (tag === 'input' && !['button','checkbox','color','file','hidden','image','radio','range','reset','submit'].includes(type));
    };
    const rememberFocus = () => { const el = deepActive(); if (isEditable(el)) lastEditable = el; };
    add(document, 'focusin', rememberFocus, true);

    function editTarget() { const current = deepActive(); return isEditable(current) ? current : lastEditable; }
    function emitInput(el, inputType, data=null) {
      try { el.dispatchEvent(new InputEvent('input', {bubbles:true, composed:true, inputType, data})); }
      catch (_) { el.dispatchEvent(new Event('input', {bubbles:true, composed:true})); }
    }
    function insertAtFocus(text) {
      const el = editTarget(); if (!el) return;
      try { el.focus({preventScroll:true}); } catch (_) { try { el.focus(); } catch (_) {} }
      const tag = String(el.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea') {
        const a = Number.isInteger(el.selectionStart) ? el.selectionStart : String(el.value || '').length;
        const b = Number.isInteger(el.selectionEnd) ? el.selectionEnd : a;
        if (typeof el.setRangeText === 'function') el.setRangeText(text, a, b, 'end'); else el.value = String(el.value || '') + text;
        emitInput(el, 'insertText', text);
      } else if (el.isContentEditable) {
        try { document.execCommand('insertText', false, text); } catch (_) { el.textContent += text; }
        emitInput(el, 'insertText', text);
      }
    }
    function backspaceAtFocus() {
      const el = editTarget(); if (!el) return;
      try { el.focus({preventScroll:true}); } catch (_) {}
      const tag = String(el.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea') {
        let a = Number.isInteger(el.selectionStart) ? el.selectionStart : String(el.value || '').length;
        let b = Number.isInteger(el.selectionEnd) ? el.selectionEnd : a;
        if (a === b && a > 0) a -= 1;
        if (typeof el.setRangeText === 'function') el.setRangeText('', a, b, 'end');
        emitInput(el, 'deleteContentBackward', null);
      } else if (el.isContentEditable) {
        try { document.execCommand('delete', false); } catch (_) {}
        emitInput(el, 'deleteContentBackward', null);
      }
    }
    function enterAtFocus() {
      const el = editTarget(); if (!el) return;
      const tag = String(el.tagName || '').toLowerCase();
      if (tag === 'textarea' || el.isContentEditable) { insertAtFocus('\n'); return; }
      try {
        el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true,composed:true}));
        if (el.form && typeof el.form.requestSubmit === 'function') el.form.requestSubmit();
        el.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true,composed:true}));
      } catch (_) {}
    }
    function setKeyboard(open) { if (keyboard) keyboard.classList.toggle('open', !!open); }
    // Expose a tiny control surface to the management plane. Remote text/key
    // entry calls hideKeyboard() so the physical overlay never blocks the page.
    state.hideKeyboard = () => setKeyboard(false);
    state.showKeyboard = () => setKeyboard(true);

    if (CONFIG.onscreen_keyboard) {
      keyboard = document.createElement('div'); keyboard.id = 'kioskctl-keyboard'; keyboard.dataset.kioskctlUi = '1';
      const rows = ['1234567890','qwertyuiop','asdfghjkl','zxcvbnm'];
      rows.forEach(chars => {
        const row = document.createElement('div'); row.className = 'kline';
        [...chars].forEach(ch => { const b=document.createElement('button'); b.type='button'; b.textContent=ch; b.dataset.char=ch; row.appendChild(b); });
        keyboard.appendChild(row);
      });
      const actions = document.createElement('div'); actions.className='kline';
      actions.innerHTML='<button type="button" class="wide" data-key="backspace">⌫</button><button type="button" class="space" data-char=" ">Space</button><button type="button" class="wide" data-key="enter">Enter</button><button type="button" class="wide" data-key="hide">Hide</button>';
      keyboard.appendChild(actions); document.body.appendChild(keyboard); cleanup.push(() => keyboard.remove());
      add(keyboard, 'pointerdown', e => e.preventDefault(), {passive:false});
      add(keyboard, 'click', e => {
        const b=e.target.closest('button'); if(!b)return;
        if(b.dataset.char != null) insertAtFocus(b.dataset.char);
        else if(b.dataset.key==='backspace') backspaceAtFocus();
        else if(b.dataset.key==='enter') enterAtFocus();
        else if(b.dataset.key==='hide') setKeyboard(false);
      });
      // Do not open from focusin alone: many pages autofocus a login/search
      // field on navigation, and remote CDP clicks also create focus. Only a
      // physical touchscreen/stylus tap should automatically open the overlay.
      add(document, 'pointerup', e => {
        if (isKioskUi(e.target) || !['touch','pen'].includes(String(e.pointerType || ''))) return;
        setTimeout(() => { if (isEditable(deepActive())) setKeyboard(true); }, 0);
      }, true);
      add(window, 'pagehide', () => setKeyboard(false), true);
      add(window, 'beforeunload', () => setKeyboard(false), true);
      setKeyboard(false);
    }

    if (CONFIG.edge_drawer) {
      const tab=document.createElement('button'); tab.id='kioskctl-edge-tab'; tab.type='button'; tab.dataset.kioskctlUi='1'; tab.textContent='‹'; tab.title='Kiosk controls';
      const panel=document.createElement('aside'); panel.id='kioskctl-edge-panel'; panel.dataset.kioskctlUi='1';
      const pages = [{name:'Home',url:CONFIG.home_url}, ...(Array.isArray(CONFIG.pages)?CONFIG.pages:[])];
      panel.innerHTML=`<h3>Kiosk controls</h3><div class="krow"><button data-act="home">Home</button><button data-act="reload">Refresh</button></div>
        <div class="krow"><button data-act="back">Back</button><button data-act="next">Next</button></div>
        <div class="krow"><button data-act="zoomout">Zoom −</button><button data-act="zoomin">Zoom +</button></div>
        ${CONFIG.onscreen_keyboard?'<div class="krow"><button data-act="keyboard">Keyboard</button></div>':''}
        <div style="margin-top:12px;color:#9fb0c2;font-size:12px">Zoom <span id="kioskctl-zoom-label">${Math.round(zoom*100)}%</span></div><div class="kpages"></div>
        <button type="button" class="kclose" data-act="close">Close</button>`;
      const pageBox=panel.querySelector('.kpages');
      pages.forEach((page,index)=>{ const b=document.createElement('button'); b.type='button'; b.className='kpage'; b.textContent=page.name||`Page ${index+1}`; b.dataset.url=page.url; pageBox.appendChild(b); });
      document.body.append(tab,panel); cleanup.push(()=>{tab.remove();panel.remove();});
      const close=()=>panel.classList.remove('open');
      add(tab,'click',()=>panel.classList.toggle('open'));
      // Touching/clicking anywhere outside an open drawer closes it while the
      // original event continues to the underlying page.
      add(document,'pointerdown',e=>{
        if (!panel.classList.contains('open')) return;
        if (panel.contains(e.target) || tab.contains(e.target)) return;
        close();
      }, {capture:true, passive:true});
      add(panel,'click',e=>{
        const b=e.target.closest('button'); if(!b)return;
        if(b.dataset.url){ noteTouch(); location.href=b.dataset.url; return; }
        switch(b.dataset.act){
          case 'home': noteTouch(); location.href=CONFIG.home_url; break;
          case 'reload': noteTouch(); location.reload(); break;
          case 'back': noteTouch(); history.back(); close(); break;
          case 'next': {
            const here=location.href; let idx=pages.findIndex(p=>here===p.url || here.startsWith(p.url)); if(idx<0)idx=0; noteTouch(); location.href=pages[(idx+1)%pages.length].url; break;
          }
          case 'zoomout': applyZoom(zoom-.1); break;
          case 'zoomin': applyZoom(zoom+.1); break;
          case 'keyboard': setKeyboard(true); close(); break;
          case 'close': close(); break;
        }
      });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
  else boot();
})();'''.replace('__CONFIG__', feature_json)


def _runtime_feature_state(self: DevTools) -> dict[str, Any]:
    """Return the feature state from the currently selected kiosk document."""
    return self._call("Runtime.evaluate", {
        "expression": "(() => ({runtime:!!window.__kioskctlRuntime,pull:!!document.getElementById('kioskctl-pull-indicator'),edge:!!document.getElementById('kioskctl-edge-tab'),keyboard:!!document.getElementById('kioskctl-keyboard'),url:String(location.href||'')}))()",
        "returnByValue": True,
    }).get("result", {}).get("value", {}) or {}


def _install_runtime_features(self: DevTools, cfg: dict[str, Any]) -> dict[str, Any]:
    """Install kiosk touch/zoom helpers for the current and future documents.

    The registration belongs to one DevTools page target. Home Assistant's
    OAuth flow can navigate/replace that target while the kiosk is starting, so
    a long-lived runtime monitor calls this again when necessary. Chromium 153
    supports Page.addScriptToEvaluateOnNewDocument; use runImmediately when the
    protocol accepts it and fall back to an explicit Runtime.evaluate for older
    builds.
    """
    script = browser_runtime_script(cfg)
    target = self.target_info()
    self._call("Page.enable")
    previous = _RUNTIME_SCRIPT_IDS.get(self.port)
    if previous:
        try:
            self._call("Page.removeScriptToEvaluateOnNewDocument", {"identifier": previous})
        except Exception:
            # Browser restarts / target replacement invalidate the old id.
            pass

    ran_immediately = False
    try:
        registered = self._call(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": script, "runImmediately": True},
        )
        ran_immediately = True
    except Exception:
        registered = self._call("Page.addScriptToEvaluateOnNewDocument", {"source": script})

    identifier = registered.get("identifier")
    if identifier:
        _RUNTIME_SCRIPT_IDS[self.port] = str(identifier)

    if not ran_immediately:
        # addScript... without runImmediately only affects the next document.
        self._call("Runtime.evaluate", {"expression": script, "returnByValue": False, "awaitPromise": False})

    features = browser_runtime_config(cfg)
    expected = {
        "pull": bool(features.get("pull_to_refresh")),
        "edge": bool(features.get("edge_drawer")),
        "keyboard": bool(features.get("onscreen_keyboard")),
    }
    deadline = time.monotonic() + 1.25
    check: dict[str, Any] = {}
    while time.monotonic() < deadline:
        check = self.runtime_feature_state()
        missing = [name for name, wanted in expected.items() if wanted and not bool(check.get(name))]
        if check.get("runtime") and not missing:
            return {
                "ok": True,
                "identifier": identifier,
                "features": features,
                "target": target,
                "runtime": check,
            }
        time.sleep(0.08)

    missing = [name for name, wanted in expected.items() if wanted and not bool(check.get(name))]
    if missing:
        raise RuntimeError(
            "runtime feature injection did not become active for " + ", ".join(missing) +
            f" on target {check.get('url') or target.get('url') or 'unknown'}"
        )
    raise RuntimeError(
        "runtime feature bootstrap did not become active on target " +
        str(check.get("url") or target.get("url") or "unknown")
    )


DevTools.runtime_feature_state = _runtime_feature_state  # type: ignore[attr-defined]
DevTools.install_runtime_features = _install_runtime_features  # type: ignore[attr-defined]


