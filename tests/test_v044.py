import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.browser import DevTools
from kioskctl.config import load_config
from kioskctl.events import EventBus
from kioskctl.plugins.homeassistant import HomeAssistantPlugin

ROOT = Path(__file__).resolve().parents[1]


class FakeMQTT:
    def __init__(self):
        self.device_id = "archkiosk"
        self.base = "kioskctl/archkiosk"
        self.connected = True
        self.published = []
        self.connect_listeners = []
        self.subscriptions = {}

    def add_connect_listener(self, cb): self.connect_listeners.append(cb)
    def subscribe(self, topic, cb): self.subscriptions[topic] = cb
    def publish_json(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain)); return True
    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain)); return True


class V044RegressionTests(unittest.TestCase):
    def test_devtools_prefers_external_kiosk_page_over_chromium_webui(self):
        dt = DevTools(9222, "https://hass.example/home/overview")
        dt._targets = lambda: [
            {"type": "page", "url": "chrome://newtab/", "title": "New Tab", "id": "internal"},
            {"type": "page", "url": "https://hass.example/home/overview", "title": "Home Assistant", "id": "kiosk"},
        ]
        self.assertEqual(dt._page()["id"], "kiosk")
        self.assertEqual(dt.current_url(), "https://hass.example/home/overview")

    def test_devtools_prefers_same_origin_for_secondary_page(self):
        dt = DevTools(9222, "https://hass.example/home/overview")
        dt._targets = lambda: [
            {"type": "page", "url": "https://unrelated.example/", "id": "other"},
            {"type": "page", "url": "https://hass.example/cameras", "id": "kiosk"},
        ]
        self.assertEqual(dt._page()["id"], "kiosk")

    def test_homeassistant_current_url_template_falls_back_on_empty_url(self):
        cfg = load_config(Path("/definitely/not/present"))
        cfg["device"]["name"] = "archkiosk"
        cfg["plugins"]["homeassistant"]["enabled"] = True
        mqtt = FakeMQTT()
        plugin = HomeAssistantPlugin(cfg, mqtt, EventBus(), lambda: {}, "0.5.2")
        _component, entity = plugin._entities()["current_url"]
        self.assertIn("if value_json.current_url else value_json.configured_url", entity["value_template"])

    def test_brightness_and_volume_are_clamped_before_provider_call(self):
        old = os.environ.get("KIOSKCTL_CONFIG")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["KIOSKCTL_CONFIG"] = str(Path(td) / "config.yaml")
                sys.modules.pop("kioskctl.main", None)
                main = importlib.import_module("kioskctl.main")

                seen = {"brightness": None, "volume": None}
                class FakeTools:
                    def __init__(self, cfg): pass
                    def set_brightness(self, percent): seen["brightness"] = percent
                    def set_volume(self, percent): seen["volume"] = percent; return "fake"

                with patch.object(main, "WaylandTools", FakeTools):
                    b = main.brightness(main.PercentBody(percent=150))
                    v = main.volume(main.PercentBody(percent=-20))
                self.assertEqual(seen["brightness"], 100)
                self.assertEqual(b["percent"], 100)
                self.assertEqual(seen["volume"], 0)
                self.assertEqual(v["percent"], 0)
        finally:
            sys.modules.pop("kioskctl.main", None)
            if old is None:
                os.environ.pop("KIOSKCTL_CONFIG", None)
            else:
                os.environ["KIOSKCTL_CONFIG"] = old

    def test_runtime_feature_installer_reports_target_and_verifies_overlays(self):
        source = (ROOT / "kioskctl/browser.py").read_text()
        self.assertIn("runtime feature injection did not become active", source)
        self.assertIn("target_info", source)
        self.assertIn("kioskctl-edge-tab", source)
        self.assertIn("kioskctl-keyboard", source)

    def test_version_044_is_synchronized(self):
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / "install.sh").read_text())
        self.assertIn('__version__ = "0.5.2"', (ROOT / "kioskctl/__init__.py").read_text())
        self.assertIn('APP_VERSION = "0.5.2"', (ROOT / "kioskctl/main.py").read_text())
        self.assertIn('version = "0.5.2"', (ROOT / "pyproject.toml").read_text())
        html = (ROOT / "kioskctl/static/index.html").read_text()
        self.assertIn("v0.5.2", html)
        self.assertIn("app.js?v=0.5.2", html)


if __name__ == "__main__":
    unittest.main()
