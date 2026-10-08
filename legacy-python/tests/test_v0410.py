import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.browser import DevTools, browser_runtime_script
from kioskctl.config import DEFAULT_CONFIG, load_config
from kioskctl.platform import touch_pointer_suppression_status

ROOT = Path(__file__).resolve().parents[1]


class V0410RegressionTests(unittest.TestCase):
    def test_v7_config_migrates_to_v8_pointer_suppression_default(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.yaml"
            p.write_text("version: 7\ndevice:\n  name: kiosk\n")
            cfg = load_config(p)
        self.assertEqual(cfg["version"], 10)
        self.assertTrue(cfg["input"]["ignore_touch_mouse_emulation"])

    def test_pointer_suppression_only_targets_mouse_nodes_paired_with_touch(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        devices = [
            {"name": "Touch", "type": "touchscreen", "event": "event6", "phys": "i2c-foo", "udev": {}},
            {"name": "Touch Mouse", "type": "mouse", "event": "event10", "phys": "i2c-foo", "udev": {"LIBINPUT_IGNORE_DEVICE": "1"}},
            {"name": "USB Mouse", "type": "mouse", "event": "event20", "phys": "usb-bar", "udev": {}},
            {"name": "Touchpad", "type": "touchpad", "event": "event5", "phys": "i2c-pad", "udev": {}},
        ]
        with patch("kioskctl.platform.input_devices", return_value=devices):
            status = touch_pointer_suppression_status(cfg)
        self.assertEqual([x["event"] for x in status["candidates"]], ["event10"])
        self.assertEqual(status["active_count"], 1)

    def test_edge_drawer_closes_on_outside_pointerdown(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["browser"]["touch_ui"]["edge_drawer"] = True
        js = browser_runtime_script(cfg)
        self.assertIn("if (!panel.classList.contains('open')) return", js)
        self.assertIn("panel.contains(e.target) || tab.contains(e.target)", js)
        self.assertIn("add(document,'pointerdown'", js)

    def test_devtools_replace_uses_location_replace(self):
        dt = DevTools(9222, "https://example.com")
        with patch.object(dt, "bring_to_front"), patch.object(dt, "_call", return_value={}) as call:
            dt.replace("https://example.org/path?q=1")
        method, params = call.call_args.args
        self.assertEqual(method, "Runtime.evaluate")
        self.assertIn("location.replace", params["expression"])
        self.assertIn("https://example.org/path?q=1", params["expression"])

    def test_idle_manager_uses_replace_for_screensaver_history(self):
        source = (ROOT / "kioskctl/idle.py").read_text()
        self.assertIn("dt.replace(target)", source)
        self.assertNotIn("dt.navigate(target)", source)

    def test_webui_exposes_pointer_suppression_and_refreshes_assets(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        js = (ROOT / "kioskctl/static/app.js").read_text()
        self.assertIn('id="ignoreTouchMouse"', html)
        self.assertIn('id="touchPointerInfo"', html)
        self.assertIn("ignore_touch_mouse_emulation:$('ignoreTouchMouse').checked", js)
        self.assertIn("async function refreshScreensaverAssets()", js)
        self.assertIn("api('screensaver/images')", js)

    def test_version_0410_is_synchronized(self):
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
