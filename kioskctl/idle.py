from __future__ import annotations

import logging
import os
import select
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from .platform import WaylandTools, input_devices
from .browser import DevTools

logger = logging.getLogger("kioskctl.idle")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IdleManager:
    """Best-effort idle/dim/off policy with wake-on-local-input.

    The management agent runs as root, so it can watch the same evdev devices
    libinput/Cage reads without grabbing them. Reads are non-exclusive: Cage
    continues to receive the input normally. We deliberately monitor only
    human-input classes to avoid audio jack/lid-switch noise waking the screen.
    """

    HUMAN_TYPES = {"touchscreen", "touchpad", "tablet", "keyboard", "mouse"}

    def __init__(self, get_config: Callable[[], dict[str, Any]], get_screensaver_provider: Callable[[], Any | None] | None = None) -> None:
        self.get_config = get_config
        self.get_screensaver_provider = get_screensaver_provider
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._last_activity_mono = time.monotonic()
        self._last_activity = _now()
        self._state = "active"
        self._saved_brightness: int | None = None
        self._last_error: str | None = None
        self._monitored: list[str] = []
        self._wake_count = 0
        self._dim_count = 0
        self._off_count = 0
        self._screensaver_active = False
        self._screensaver_return_url: str | None = None
        self._screensaver_count = 0
        self._screensaver_error: str | None = None
        self._screensaver_preview = False
        self._screensaver_provider_id = "core"
        self._screensaver_provider_name = "Simple screensaver"
        self._screensaver_provider_obj: Any | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="kioskctl-idle")
        self._thread.start()
        logger.info("Idle manager started")

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._thread = None

    def notify_activity(self, source: str = "api") -> None:
        with self._lock:
            self._last_activity_mono = time.monotonic()
            self._last_activity = _now()
        self._wake_if_needed(source)

    def wake(self, source: str = "api") -> None:
        with self._lock:
            self._last_activity_mono = time.monotonic()
            self._last_activity = _now()
        self._wake_if_needed(source, force=True)

    def status(self) -> dict[str, Any]:
        cfg = self.get_config().get("idle", {})
        with self._lock:
            elapsed = max(0.0, time.monotonic() - self._last_activity_mono)
            return {
                "enabled": bool(cfg.get("enabled", False)),
                "state": self._state,
                "idle_seconds": int(elapsed),
                "last_activity": self._last_activity,
                "wake_on_input": bool(cfg.get("wake_on_input", True)),
                "dim_after_seconds": int(cfg.get("dim_after_seconds", 300)),
                "off_after_seconds": int(cfg.get("off_after_seconds", 600)),
                "dim_brightness": int(cfg.get("dim_brightness", 20)),
                "monitored_devices": list(self._monitored),
                "last_error": self._last_error,
                "wake_count": self._wake_count,
                "dim_count": self._dim_count,
                "off_count": self._off_count,
                "screensaver_active": self._screensaver_active,
                "screensaver_count": self._screensaver_count,
                "screensaver_error": self._screensaver_error,
                "screensaver_preview": self._screensaver_preview,
                "screensaver_provider": self._screensaver_provider_id,
                "screensaver_provider_name": self._screensaver_provider_name,
            }

    def _human_event_paths(self) -> list[str]:
        paths: list[str] = []
        for dev in input_devices():
            if str(dev.get("type")) not in self.HUMAN_TYPES:
                continue
            event = str(dev.get("event") or "")
            if event.startswith("event"):
                path = f"/dev/input/{event}"
                if os.path.exists(path) and path not in paths:
                    paths.append(path)
        return paths

    def _open_devices(self) -> dict[int, str]:
        opened: dict[int, str] = {}
        for path in self._human_event_paths():
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                opened[fd] = path
            except OSError:
                continue
        with self._lock:
            self._monitored = list(opened.values())
        return opened

    @staticmethod
    def _close_devices(opened: dict[int, str]) -> None:
        for fd in list(opened):
            try:
                os.close(fd)
            except OSError:
                pass

    def _plugin_screensaver_provider(self) -> Any | None:
        if self.get_screensaver_provider is None:
            return None
        try:
            return self.get_screensaver_provider()
        except Exception:
            logger.exception("Unable to select plugin screensaver provider")
            return None

    def _screensaver_url(self, cfg: dict[str, Any], provider: Any | None = None) -> str:
        port = int(cfg.get("admin", {}).get("port", 2324) or 2324)
        if provider is not None and hasattr(provider, "screen_url"):
            return str(provider.screen_url(port))
        return f"http://127.0.0.1:{port}/screensaver"

    @staticmethod
    def _screensaver_keeps_display_on(cfg: dict[str, Any], provider: Any | None = None) -> bool:
        if provider is not None:
            try:
                return bool(provider.keep_display_on)
            except Exception:
                return True
        return bool(cfg.get("screensaver", {}).get("keep_display_on", True))

    def _ensure_display_active_for_screensaver(self, cfg: dict[str, Any], provider: Any | None = None) -> None:
        """Restore the panel before showing signage when configured to stay on.

        A slideshow and the idle display-off policy can share the same inactivity
        clock.  Without coordination, both may fire in the same policy pass: the
        browser navigates to the slideshow and the display is powered off a few
        lines later.  Treat an active slideshow as visible signage by default.
        """
        if not self._screensaver_keeps_display_on(cfg, provider):
            return
        with self._lock:
            state = self._state
            saved = self._saved_brightness
        if state == "active":
            return
        tools = WaylandTools(cfg)
        if state == "off":
            tools.display_power(True)
        if saved is not None:
            try:
                tools.set_brightness(saved)
            except Exception:
                logger.debug("Unable to restore brightness for screensaver", exc_info=True)
        with self._lock:
            self._state = "active"
            self._saved_brightness = None
            self._last_error = None
        logger.info("Idle display policy yielded to active slideshow screensaver")

    def _show_screensaver(self, cfg: dict[str, Any], *, preview: bool = False, provider: Any | None = None) -> None:
        with self._lock:
            if self._screensaver_active:
                return
        try:
            self._ensure_display_active_for_screensaver(cfg, provider)
            browser = cfg.get("browser", {})
            dt = DevTools(int(browser.get("devtools_port", 9222)), str(browser.get("url", "")))
            current = dt.current_url()
            target = self._screensaver_url(cfg, provider)
            if current and not current.startswith(target):
                with self._lock:
                    self._screensaver_return_url = current
            dt.replace(target)
            with self._lock:
                self._screensaver_active = True
                self._screensaver_count += 1
                self._screensaver_error = None
                self._screensaver_preview = bool(preview)
                self._screensaver_provider_obj = provider
                self._screensaver_provider_id = str(getattr(provider, "id", "core")) if provider is not None else "core"
                self._screensaver_provider_name = str(getattr(provider, "name", "Simple screensaver")) if provider is not None else "Simple screensaver"
            logger.info("Screensaver started via %s", self._screensaver_provider_name)
        except Exception as exc:
            with self._lock:
                self._screensaver_error = str(exc)
            logger.debug("Unable to start screensaver: %s", exc)

    def _hide_screensaver(self, cfg: dict[str, Any], source: str) -> None:
        with self._lock:
            active = self._screensaver_active
            return_url = self._screensaver_return_url
        if not active:
            return
        try:
            browser = cfg.get("browser", {})
            dt = DevTools(int(browser.get("devtools_port", 9222)), str(browser.get("url", "")))
            target = return_url or str(browser.get("url", "https://example.com"))
            dt.replace(target)
            logger.info("Screensaver dismissed by %s", source)
        except Exception as exc:
            logger.debug("Unable to restore page after screensaver: %s", exc)
        finally:
            with self._lock:
                self._screensaver_active = False
                self._screensaver_return_url = None
                self._screensaver_preview = False
                self._screensaver_provider_obj = None
                self._screensaver_provider_id = "core"
                self._screensaver_provider_name = "Simple screensaver"

    def preview_screensaver(self, provider: Any | None = None) -> None:
        cfg = self.get_config()
        # A preview may already be active when the operator changes fit,
        # background, interval, or provider settings. Reload the preview so the
        # freshly saved configuration is visible immediately instead of keeping
        # the old slideshow document alive.
        with self._lock:
            active = self._screensaver_active
        if active:
            self._hide_screensaver(cfg, "preview-refresh")
        self._show_screensaver(cfg, preview=True, provider=provider)

    def stop_screensaver(self, source: str = "api") -> None:
        cfg = self.get_config()
        self._hide_screensaver(cfg, source)
        with self._lock:
            self._last_activity_mono = time.monotonic()
            self._last_activity = _now()

    def _wake_if_needed(self, source: str, force: bool = False) -> None:
        cfg = self.get_config()
        idle = cfg.get("idle", {})
        if not force and not bool(idle.get("wake_on_input", True)):
            return
        with self._lock:
            state = self._state
            saved = self._saved_brightness
            screensaver_active = self._screensaver_active
        if screensaver_active:
            self._hide_screensaver(cfg, source)
        if state == "active":
            return
        try:
            tools = WaylandTools(cfg)
            if state == "off":
                tools.display_power(True)
            if saved is not None:
                try:
                    tools.set_brightness(saved)
                except Exception:
                    logger.debug("Unable to restore brightness after idle wake", exc_info=True)
            with self._lock:
                self._state = "active"
                self._saved_brightness = None
                self._last_error = None
                self._wake_count += 1
            logger.info("Idle wake from %s", source)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            logger.warning("Idle wake failed: %s", exc)

    def _apply_policy(self) -> None:
        cfg = self.get_config()
        idle = cfg.get("idle", {})
        screensaver = cfg.get("screensaver", {})
        provider = self._plugin_screensaver_provider()
        with self._lock:
            elapsed = time.monotonic() - self._last_activity_mono
            screen_active = self._screensaver_active
            active_provider_id = self._screensaver_provider_id

        # An installed/enabled plugin screensaver supersedes the simple core
        # screensaver. If the provider is temporarily unavailable (for example
        # outside a signage schedule), we intentionally do not fall back to the
        # core slideshow and surprise the operator with different content.
        if provider is not None:
            provider_id = str(getattr(provider, "id", "plugin"))
            try:
                available = bool(provider.available_now())
                after = max(1, int(provider.after_seconds))
            except Exception as exc:
                available = False
                after = 120
                with self._lock:
                    self._screensaver_error = str(exc)
            if screen_active and active_provider_id not in {provider_id, "core"}:
                self._hide_screensaver(cfg, "screensaver-provider-changed")
                screen_active = False
            if available and elapsed >= after and not screen_active:
                self._show_screensaver(cfg, provider=provider)
            elif screen_active and active_provider_id == provider_id and not available:
                with self._lock:
                    preview = self._screensaver_preview
                if not preview:
                    self._hide_screensaver(cfg, "screensaver-provider-unavailable")
        else:
            if bool(screensaver.get("enabled", False)):
                after = int(screensaver.get("after_seconds", 120) or 120)
                if elapsed >= after and not screen_active:
                    self._show_screensaver(cfg)
            elif screen_active and active_provider_id == "core":
                with self._lock:
                    preview = self._screensaver_preview
                if not preview:
                    self._hide_screensaver(cfg, "screensaver-disabled")

        # Re-read after _show_screensaver(), since it may have become active in
        # this same policy pass. Visible signage wins over dim/off by default.
        with self._lock:
            screen_active = self._screensaver_active
            active_provider = self._screensaver_provider_obj
        if screen_active and self._screensaver_keeps_display_on(cfg, active_provider):
            try:
                self._ensure_display_active_for_screensaver(cfg, active_provider)
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                logger.debug("Unable to keep display on for screensaver: %s", exc)
            return

        if not bool(idle.get("enabled", False)):
            with self._lock:
                state = self._state
            if state != "active":
                # Restore display power/brightness without dismissing a local
                # slideshow that may be independently enabled.
                try:
                    tools = WaylandTools(cfg)
                    if state == "off":
                        tools.display_power(True)
                    if self._saved_brightness is not None:
                        try:
                            tools.set_brightness(self._saved_brightness)
                        except Exception:
                            pass
                    with self._lock:
                        self._state = "active"
                        self._saved_brightness = None
                except Exception:
                    pass
            return

        dim_after = int(idle.get("dim_after_seconds", 300) or 0)
        off_after = int(idle.get("off_after_seconds", 600) or 0)
        dim_brightness = int(idle.get("dim_brightness", 20) or 20)
        with self._lock:
            elapsed = time.monotonic() - self._last_activity_mono
            state = self._state

        try:
            tools = WaylandTools(cfg)
            if off_after > 0 and elapsed >= off_after and state != "off":
                if state == "active":
                    try:
                        self._saved_brightness = tools.get_brightness()
                    except Exception:
                        self._saved_brightness = None
                tools.display_power(False)
                with self._lock:
                    self._state = "off"
                    self._off_count += 1
                    self._last_error = None
                logger.info("Idle policy turned display off after %ss", int(elapsed))
            elif dim_after > 0 and elapsed >= dim_after and state == "active":
                try:
                    self._saved_brightness = tools.get_brightness()
                except Exception:
                    self._saved_brightness = None
                tools.set_brightness(dim_brightness)
                with self._lock:
                    self._state = "dimmed"
                    self._dim_count += 1
                    self._last_error = None
                logger.info("Idle policy dimmed display to %s%%", dim_brightness)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            logger.debug("Idle policy action failed: %s", exc)

    def _run(self) -> None:
        opened: dict[int, str] = {}
        next_rescan = 0.0
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now >= next_rescan or not opened:
                    self._close_devices(opened)
                    opened = self._open_devices()
                    next_rescan = now + 30.0

                ready: list[int] = []
                if opened:
                    try:
                        ready, _, _ = select.select(list(opened), [], [], 1.0)
                    except (OSError, ValueError):
                        self._close_devices(opened)
                        opened = {}
                else:
                    self._stop.wait(1.0)

                activity = False
                for fd in ready:
                    try:
                        data = os.read(fd, 4096)
                        if data:
                            activity = True
                    except BlockingIOError:
                        pass
                    except OSError:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                        opened.pop(fd, None)
                if activity:
                    with self._lock:
                        self._last_activity_mono = time.monotonic()
                        self._last_activity = _now()
                    self._wake_if_needed("local-input")
                self._apply_policy()
        finally:
            self._close_devices(opened)
