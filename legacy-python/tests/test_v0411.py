import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.config import DEFAULT_CONFIG, load_config
from kioskctl.platform import install_touchpad_suppression, touchpad_suppression_status

ROOT = Path(__file__).resolve().parents[1]


class V0411RegressionTests(unittest.TestCase):
    def test_v8_config_migrates_to_v9_touchpad_default(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.yaml"
            p.write_text("version: 8\ndevice:\n  name: kiosk\n")
            cfg = load_config(p)
        self.assertEqual(cfg["version"], 10)
        self.assertFalse(cfg["input"]["disable_touchpad_in_kiosk"])

    def test_touchpad_suppression_targets_only_touchpads(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["input"]["disable_touchpad_in_kiosk"] = True
        devices = [
            {"name": "Elan Touchpad", "type": "touchpad", "event": "event5", "phys": "", "udev": {"LIBINPUT_IGNORE_DEVICE": "1"}},
            {"name": "Touch", "type": "touchscreen", "event": "event6", "phys": "i2c-touch", "udev": {}},
            {"name": "USB Mouse", "type": "mouse", "event": "event20", "phys": "usb-mouse", "udev": {}},
        ]
        with patch("kioskctl.platform.input_devices", return_value=devices):
            status = touchpad_suppression_status(cfg)
        self.assertEqual([x["event"] for x in status["candidates"]], ["event5"])
        self.assertEqual(status["active_count"], 1)

    def test_touchpad_rule_is_reversible(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["input"]["disable_touchpad_in_kiosk"] = True
        devices = [{"name": "Elan Touchpad", "type": "touchpad", "event": "event5", "phys": "", "udev": {}}]
        with tempfile.TemporaryDirectory() as td:
            rule = Path(td) / "99-kioskctl-touchpad.rules"
            with patch("kioskctl.platform.TOUCHPAD_RULE_PATH", rule), \
                 patch("kioskctl.platform.input_devices", return_value=devices), \
                 patch("kioskctl.platform.os.geteuid", return_value=0), \
                 patch("kioskctl.platform.shutil.which", return_value=None):
                result = install_touchpad_suppression(cfg, reload_rules=False)
                self.assertTrue(rule.exists())
                self.assertIn('ENV{ID_INPUT_TOUCHPAD}=="1"', rule.read_text())
                self.assertTrue(result["changed"])
                install_touchpad_suppression(cfg, reload_rules=False, force_enabled=False)
                self.assertFalse(rule.exists())

    def test_webui_exposes_kiosk_touchpad_toggle(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        js = (ROOT / "kioskctl/static/app.js").read_text()
        self.assertIn('id="disableTouchpad"', html)
        self.assertIn('id="touchpadInfo"', html)
        self.assertIn("disable_touchpad_in_kiosk:$('disableTouchpad').checked", js)
        self.assertIn("touchpad_suppression", js)

    def test_session_restores_touchpad_when_kiosk_disabled(self):
        source = (ROOT / "kioskctl/session.py").read_text()
        self.assertIn("install_touchpad_suppression(cfg, reload_rules=True)", source)
        self.assertIn("install_touchpad_suppression(cfg, reload_rules=True, force_enabled=False)", source)

    def test_version_0411_is_synchronized(self):
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
