import copy
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call

from kioskctl.browser import DevTools, browser_runtime_script
from kioskctl.config import DEFAULT_CONFIG

ROOT = Path(__file__).resolve().parents[1]


class V047Tests(unittest.TestCase):
    def test_dark_mode_uses_media_preference_and_auto_dark_override(self):
        dt = DevTools.__new__(DevTools)
        dt.port = 9222
        dt.preferred_url = ""
        dt._call = MagicMock(return_value={})
        self.assertEqual(dt.set_color_scheme("dark"), "dark")
        self.assertIn(
            call("Emulation.setEmulatedMedia", {"media": "", "features": [{"name": "prefers-color-scheme", "value": "dark"}]}),
            dt._call.call_args_list,
        )
        self.assertIn(call("Emulation.setAutoDarkModeOverride", {"enabled": True}), dt._call.call_args_list)

    def test_light_and_auto_clear_forced_dark_override(self):
        dt = DevTools.__new__(DevTools)
        dt.port = 9222
        dt.preferred_url = ""
        dt._call = MagicMock(return_value={})
        dt.set_color_scheme("light")
        self.assertIn(call("Emulation.setAutoDarkModeOverride", {"enabled": False}), dt._call.call_args_list)
        dt._call.reset_mock()
        dt.set_color_scheme("auto")
        self.assertIn(call("Emulation.setAutoDarkModeOverride", {}), dt._call.call_args_list)

    def test_runtime_uses_touch_events_for_pull_to_refresh(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["browser"]["touch_ui"]["pull_to_refresh"] = True
        script = browser_runtime_script(cfg)
        self.assertIn("'touchstart'", script)
        self.assertIn("'touchmove'", script)
        self.assertIn("{capture:true, passive:false}", script)
        self.assertIn("overscrollBehaviorY = 'contain'", script)
        self.assertNotIn("add(window, 'pointercancel', reset", script)

    def test_runtime_keyboard_is_remote_hideable_and_touch_open_only(self):
        script = browser_runtime_script(DEFAULT_CONFIG)
        self.assertIn("state.hideKeyboard = () => setKeyboard(false)", script)
        self.assertIn("['touch','pen'].includes", script)
        self.assertIn("setKeyboard(false);", script)
        self.assertNotIn("add(document, 'focusin', () => { if (isEditable(deepActive())) setKeyboard(true); }", script)
        source = (ROOT / "kioskctl/browser.py").read_text()
        self.assertIn("self.hide_runtime_keyboard()", source)

    def test_runtime_autohides_cursor(self):
        script = browser_runtime_script(DEFAULT_CONFIG)
        self.assertIn("kioskctl-cursor-hidden", script)
        self.assertIn("cursorWatchdog", script)
        self.assertIn("performance.now() - lastRealMouseAt >= 1800", script)

    def test_dashboard_health_indicators_are_in_sticky_header(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        css = (ROOT / "kioskctl/static/style.css").read_text()
        js = (ROOT / "kioskctl/static/app.js").read_text()
        self.assertIn('class="header-health hidden" id="healthIndicators"', html)
        self.assertNotIn('class="card health-card"', html)
        self.assertIn("header-health-item", css)
        self.assertIn("target!=='dashboard'", js)

    def test_version_047_is_synchronized(self):
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
