import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.config import DEFAULT_CONFIG, load_config
from kioskctl.idle import IdleManager
from kioskctl.browser import browser_runtime_script

ROOT = Path(__file__).resolve().parents[1]


class _FakeWaylandTools:
    instances = []

    def __init__(self, cfg):
        self.cfg = cfg
        self.power_calls = []
        self.brightness_calls = []
        self.__class__.instances.append(self)

    def display_power(self, enabled):
        self.power_calls.append(bool(enabled))

    def get_brightness(self):
        return 75

    def set_brightness(self, value):
        self.brightness_calls.append(int(value))


class V049RegressionTests(unittest.TestCase):
    def test_v6_config_migrates_to_v7_and_screensaver_keeps_display_on(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.yaml"
            p.write_text("version: 6\ndevice:\n  name: kiosk\n")
            cfg = load_config(p)
        self.assertEqual(cfg["version"], 10)
        self.assertTrue(cfg["screensaver"]["keep_display_on"])

    def test_active_screensaver_prevents_idle_display_off_by_default(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["idle"].update({"enabled": True, "dim_after_seconds": 1, "off_after_seconds": 2})
        cfg["screensaver"].update({"enabled": True, "after_seconds": 2, "keep_display_on": True})
        mgr = IdleManager(lambda: cfg)
        mgr._last_activity_mono = time.monotonic() - 5

        def fake_show(_cfg, preview=False):
            with mgr._lock:
                mgr._screensaver_active = True
                mgr._screensaver_preview = preview

        _FakeWaylandTools.instances.clear()
        with patch("kioskctl.idle.WaylandTools", _FakeWaylandTools), patch.object(mgr, "_show_screensaver", fake_show):
            mgr._apply_policy()

        self.assertTrue(mgr._screensaver_active)
        self.assertEqual(mgr._state, "active")
        self.assertFalse(any(False in x.power_calls for x in _FakeWaylandTools.instances))

    def test_runtime_cursor_uses_watchdog_and_explicit_touch_hide(self):
        js = browser_runtime_script(DEFAULT_CONFIG)
        self.assertIn("cursorWatchdog", js)
        self.assertIn("lastRealMouseAt", js)
        self.assertIn("noteTouch(); location.reload()", js)
        self.assertIn("performance.now() - lastRealMouseAt >= 1800", js)

    def test_runtime_monitor_skips_local_screensaver_injection(self):
        source = (ROOT / "kioskctl/runtime_monitor.py").read_text()
        self.assertIn('"/screensaver" in url', source)
        self.assertIn("valid", source)
        self.assertIn("terminal runtime", source)

    def test_dashboard_has_mode_indicator_and_system_activity_is_first(self):
        js = (ROOT / "kioskctl/static/app.js").read_text()
        html = (ROOT / "kioskctl/static/index.html").read_text()
        self.assertIn("provider_name", js)
        self.assertIn("SAVER", js)
        self.assertIn("SLEEP", js)
        self.assertIn("screensaverKeepDisplayOn", html)
        system = html.split('data-view="system"', 1)[1]
        self.assertLess(system.index('<h2>Activity</h2>'), system.index('id="systemStats"'))

    def test_version_049_is_synchronized(self):
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / "install.sh").read_text())
        self.assertIn('__version__ = "0.5.2"', (ROOT / "kioskctl/__init__.py").read_text())
        self.assertIn('APP_VERSION = "0.5.2"', (ROOT / "kioskctl/main.py").read_text())
        self.assertIn('version = "0.5.2"', (ROOT / "pyproject.toml").read_text())
        html = (ROOT / "kioskctl/static/index.html").read_text()
        self.assertIn("v0.5.2", html)
        self.assertIn("app.js?v=0.5.2", html)
        self.assertIn("style.css?v=0.5.2", html)


if __name__ == "__main__":
    unittest.main()
