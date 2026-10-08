import copy
import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from kioskctl.browser import browser_runtime_config, browser_runtime_script
from kioskctl.config import DEFAULT_CONFIG, load_config, merge_preserved_integrations
from kioskctl.events import EventBus
from kioskctl.idle import IdleManager
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


class V043FeatureTests(unittest.TestCase):
    def test_v4_config_migrates_to_v5_touch_and_idle_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.yaml"
            p.write_text("version: 4\ndevice:\n  name: old\n")
            cfg = load_config(p)
        self.assertEqual(cfg["version"], 10)
        self.assertTrue(cfg["browser"]["touch_ui"]["pull_to_refresh"])
        self.assertEqual(cfg["browser"]["zoom"], 1.0)
        self.assertFalse(cfg["idle"]["enabled"])
        self.assertTrue(cfg["idle"]["wake_on_input"])

    def test_browser_runtime_script_has_pull_refresh_and_no_management_secrets(self):
        cfg = load_config(Path("/definitely/not/present"))
        cfg["admin"]["auth"]["token"] = "TOP-SECRET-TOKEN"
        cfg["mqtt"]["password"] = "TOP-SECRET-PASSWORD"
        cfg["browser"]["pages"] = [{"name": "Cameras", "url": "https://example.com/cameras"}]
        cfg["browser"]["touch_ui"]["edge_drawer"] = True
        script = browser_runtime_script(cfg)
        features = browser_runtime_config(cfg)
        self.assertTrue(features["pull_to_refresh"])
        self.assertIn("Release to refresh", script)
        self.assertIn("location.reload()", script)
        self.assertIn("kioskctl-edge-panel", script)
        self.assertNotIn("TOP-SECRET-TOKEN", script)
        self.assertNotIn("TOP-SECRET-PASSWORD", script)

    def test_generated_browser_runtime_script_is_valid_javascript_when_node_available(self):
        node = subprocess.run(["sh", "-c", "command -v node || true"], text=True, capture_output=True).stdout.strip()
        if not node:
            self.skipTest("node not installed")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "runtime.js"
            p.write_text(browser_runtime_script(DEFAULT_CONFIG))
            result = subprocess.run([node, "--check", str(p)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_plugin_manifest_and_expanded_homeassistant_entities(self):
        cfg = load_config(Path("/definitely/not/present"))
        cfg["device"]["name"] = "archkiosk"
        cfg["plugins"]["homeassistant"]["enabled"] = True
        cfg["browser"]["pages"] = [{"name": "Cameras", "url": "https://example.com/cameras"}]
        mqtt = FakeMQTT()
        status = MagicMock(return_value={"current_url": "https://example.com", "configured_url": "https://example.com"})
        plugin = HomeAssistantPlugin(cfg, mqtt, EventBus(), status, "0.5.2")
        result = plugin.publish_discovery()
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["entities"], 20)
        self.assertIn("homeassistant.discovery", plugin.manifest.capabilities)
        payloads = {topic: payload for topic, payload, _ in mqtt.published if topic.endswith("/config")}
        self.assertIn("homeassistant/number/kioskctl_archkiosk/zoom/config", payloads)
        self.assertIn("homeassistant/select/kioskctl_archkiosk/page/config", payloads)
        self.assertIn("homeassistant/switch/kioskctl_archkiosk/idle/config", payloads)
        current_url = payloads["homeassistant/sensor/kioskctl_archkiosk/current_url/config"]
        self.assertIn("configured_url", current_url["value_template"])
        self.assertTrue(any(topic == "kioskctl/archkiosk/state" and retain for topic, _, retain in mqtt.published))

    def test_idle_status_exposes_policy_without_starting_monitor(self):
        cfg = load_config(Path("/definitely/not/present"))
        cfg["idle"].update({"enabled": True, "dim_after_seconds": 60, "off_after_seconds": 120})
        manager = IdleManager(lambda: cfg)
        status = manager.status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["dim_after_seconds"], 60)
        self.assertEqual(status["off_after_seconds"], 120)
        self.assertEqual(status["state"], "active")

    def test_new_config_routes_bind_json_bodies(self):
        old = os.environ.get("KIOSKCTL_CONFIG")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.yaml"
            os.environ["KIOSKCTL_CONFIG"] = str(path)
            sys.modules.pop("kioskctl.main", None)
            main = importlib.import_module("kioskctl.main")
            routes = {getattr(r, "path", ""): r for r in main.app.routes}
            for route_path in ("/api/browser/experience", "/api/idle/config"):
                route = routes[route_path]
                self.assertEqual([p.name for p in route.dependant.body_params], ["body"])
        sys.modules.pop("kioskctl.main", None)
        if old is None: os.environ.pop("KIOSKCTL_CONFIG", None)
        else: os.environ["KIOSKCTL_CONFIG"] = old

    def test_frontend_exposes_pull_refresh_pages_zoom_keyboard_and_idle(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        js = (ROOT / "kioskctl/static/app.js").read_text()
        for text in ("Pull down to refresh", "Browser zoom", "Configured pages", "On-screen keyboard", "Idle &amp; wake"):
            self.assertIn(text, html)
        self.assertIn("browser/experience", js)
        self.assertIn("idle/config", js)
        self.assertIn("browser/navigate", js)

    def test_preserve_integration_merge_is_narrow_and_copies_secrets(self):
        fresh = copy.deepcopy(DEFAULT_CONFIG)
        fresh["browser"]["url"] = "https://new.example"
        previous = copy.deepcopy(DEFAULT_CONFIG)
        previous["browser"]["url"] = "https://old.example"
        previous["mqtt"].update({"enabled": True, "host": "broker", "username": "u", "password": "secret"})
        previous["plugins"]["homeassistant"].update({"enabled": True, "discovery_prefix": "ha"})
        merged = merge_preserved_integrations(fresh, previous)
        self.assertEqual(merged["browser"]["url"], "https://new.example")
        self.assertEqual(merged["mqtt"]["password"], "secret")
        self.assertTrue(merged["plugins"]["homeassistant"]["enabled"])
        previous["mqtt"]["password"] = "changed"
        self.assertEqual(merged["mqtt"]["password"], "secret")

    def test_preserve_integrations_option_is_documented_and_wired(self):
        installer = (ROOT / "install.sh").read_text()
        self.assertIn("--preserve-integrations", installer)
        self.assertIn("KCFG_PRESERVE", installer)
        self.assertIn("merge_preserved_integrations", installer)

    def test_version_043_is_synchronized(self):
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / "install.sh").read_text())
        self.assertIn('__version__ = "0.5.2"', (ROOT / "kioskctl/__init__.py").read_text())
        self.assertIn('APP_VERSION = "0.5.2"', (ROOT / "kioskctl/main.py").read_text())
        self.assertIn('version = "0.5.2"', (ROOT / "pyproject.toml").read_text())
        html = (ROOT / "kioskctl/static/index.html").read_text()
        self.assertIn("v0.5.2", html)
        self.assertIn("app.js?v=0.5.2", html)


if __name__ == "__main__":
    unittest.main()
