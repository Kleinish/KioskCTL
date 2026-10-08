import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from kioskctl.config import DEFAULT_CONFIG, load_config
from kioskctl.plugins.digital_signage import DigitalSignagePlugin
from kioskctl.plugins.immich import ImmichPlugin
from kioskctl.plugins.manager import PluginManager

ROOT = Path(__file__).resolve().parents[1]


class V050RegressionTests(unittest.TestCase):
    def test_v9_config_migrates_to_v10_with_optional_plugins_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.yaml"
            p.write_text("version: 9\ndevice:\n  name: kiosk\n")
            cfg = load_config(p)
        self.assertEqual(cfg["version"], 10)
        self.assertFalse(cfg["plugins"]["digital_signage"]["installed"])
        self.assertFalse(cfg["plugins"]["immich"]["installed"])
        self.assertIn("screensaver", cfg)

    def test_plugin_catalog_exposes_optional_plugins(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        manager = PluginManager()
        manager.register(DigitalSignagePlugin(cfg))
        manager.register(ImmichPlugin(cfg))
        items = {x["id"]: x for x in manager.catalog()}
        self.assertIn("digital_signage", items)
        self.assertIn("immich", items)
        self.assertFalse(items["digital_signage"]["installed"])
        self.assertFalse(items["immich"]["installed"])
        self.assertIn("permissions", items["immich"])

    def test_screensaver_provider_is_deterministic(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["plugins"]["digital_signage"].update({"installed": True, "enabled": True})
        cfg["plugins"]["immich"].update({"installed": True, "enabled": True})
        manager = PluginManager()
        signage = DigitalSignagePlugin(cfg)
        immich = ImmichPlugin(cfg)
        manager.register(signage)
        manager.register(immich)
        self.assertIs(manager.screensaver_provider(), signage)

    def test_digital_signage_schedule_handles_overnight_window(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["plugins"]["digital_signage"].update({
            "installed": True,
            "enabled": True,
            "schedule_enabled": True,
            "schedule_start": "22:00",
            "schedule_end": "06:00",
            "schedule_days": [0, 1, 2, 3, 4, 5, 6],
        })
        p = DigitalSignagePlugin(cfg)
        self.assertTrue(p.schedule_active(datetime(2026, 9, 18, 23, 30)))
        self.assertTrue(p.schedule_active(datetime(2026, 9, 18, 5, 30)))
        self.assertFalse(p.schedule_active(datetime(2026, 9, 18, 12, 0)))

    def test_digital_signage_safe_name_rejects_non_images_and_paths(self):
        self.assertEqual(DigitalSignagePlugin.safe_name("../ad.jpg"), "ad.jpg")
        with self.assertRaises(ValueError):
            DigitalSignagePlugin.safe_name("payload.html")

    def test_immich_asset_parser_filters_non_images(self):
        payload = {"assets": [
            {"id": "image-1", "type": "IMAGE", "originalFileName": "one.jpg"},
            {"id": "video-1", "type": "VIDEO", "originalFileName": "clip.mp4"},
            {"id": "image-2", "type": "PHOTO"},
            {"type": "IMAGE"},
        ]}
        out = ImmichPlugin._asset_list(payload)
        self.assertEqual([x["id"] for x in out], ["image-1", "image-2"])

    def test_immich_status_never_returns_api_key(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["plugins"]["immich"].update({"installed": True, "api_key": "secret-token"})
        s = ImmichPlugin(cfg).status()
        self.assertTrue(s["api_key_set"])
        self.assertNotIn("api_key", s)
        self.assertNotIn("secret-token", repr(s))

    def test_runtime_monitor_skips_all_idle_content_surfaces(self):
        source = (ROOT / "kioskctl/runtime_monitor.py").read_text()
        self.assertIn('"/screensaver" in url', source)
        self.assertIn('"/plugin/digital-signage/" in url', source)
        self.assertIn('"/plugin/immich/" in url', source)

    def test_web_ui_has_catalog_and_simple_screensaver(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        self.assertIn("Simple screensaver", html)
        self.assertIn("Plugin catalog", html)
        self.assertIn("Digital Signage", html)
        self.assertIn("Immich Screensaver", html)
        self.assertIn("installSignage", html)
        self.assertIn("installImmich", html)

    def test_version_050_is_synchronized(self):
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / "install.sh").read_text())
        self.assertIn('__version__ = "0.5.2"', (ROOT / "kioskctl/__init__.py").read_text())
        self.assertIn('APP_VERSION = "0.5.2"', (ROOT / "kioskctl/main.py").read_text())
        self.assertIn('version = "0.5.2"', (ROOT / "pyproject.toml").read_text())
        self.assertTrue((ROOT / "docs/RELEASE-0.5.2.md").is_file())


if __name__ == "__main__":
    unittest.main()
