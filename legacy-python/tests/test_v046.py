import copy
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from kioskctl.browser import DevTools, browser_runtime_config, browser_runtime_script
from kioskctl.config import DEFAULT_CONFIG, _validate_config
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
    def publish_json(self, topic, payload, retain=False): self.published.append((topic, payload, retain)); return True
    def publish(self, topic, payload, retain=False): self.published.append((topic, payload, retain)); return True


class V046Tests(unittest.TestCase):
    def test_remote_page_color_scheme_uses_devtools_emulation(self):
        dt = DevTools.__new__(DevTools)
        dt.port = 9222
        dt.preferred_url = ""
        dt._call = MagicMock(return_value={})
        self.assertEqual(dt.set_color_scheme("dark"), "dark")
        self.assertTrue(any(c.args[0] == "Emulation.setEmulatedMedia" and c.args[1]["features"] == [{"name": "prefers-color-scheme", "value": "dark"}] for c in dt._call.call_args_list))
        self.assertEqual(dt.set_color_scheme("auto"), "auto")
        self.assertTrue(any(c.args[0] == "Emulation.setEmulatedMedia" and c.args[1]["features"] == [] for c in dt._call.call_args_list))

    def test_config_has_monitoring_thresholds_and_color_scheme(self):
        cfg = _validate_config(copy.deepcopy(DEFAULT_CONFIG))
        self.assertEqual(cfg["browser"]["color_scheme"], "auto")
        self.assertEqual(cfg["monitoring"]["thresholds"]["cpu_percent"], 90)
        cfg["monitoring"]["thresholds"]["temperature_c"] = 151
        with self.assertRaises(ValueError):
            _validate_config(cfg)

    def test_kiosk_drawer_close_is_bottom_red_control(self):
        script = browser_runtime_script(DEFAULT_CONFIG)
        self.assertIn('class="kclose" data-act="close"', script)
        self.assertIn('#kioskctl-edge-panel .kclose{margin-top:auto', script)
        self.assertIn('background:#b52d38', script)

    def test_admin_navigation_groups_browser_and_display_under_settings(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        js = (ROOT / "kioskctl/static/app.js").read_text()
        self.assertIn('data-view-target="dashboard"', html)
        self.assertIn('data-view-target="settings"', html)
        self.assertIn('data-settings-target="browser"', html)
        self.assertIn('data-settings-target="display"', html)
        self.assertNotIn('data-view-target="browser"', html)
        self.assertNotIn('data-view-target="display"', html)
        self.assertIn("if(requested==='overview') requested='dashboard'", js)

    def test_dashboard_indicator_threshold_ui_and_system_metrics(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        js = (ROOT / "kioskctl/static/app.js").read_text()
        self.assertIn('id="healthIndicators"', html)
        self.assertIn('id="systemStats"', html)
        self.assertIn('id="cpuThreshold"', html)
        self.assertIn("monitoring/config", js)
        self.assertIn("renderHealthIndicators", js)
        self.assertIn("renderSystemMetrics", js)

    def test_remote_url_has_hover_title_and_page_theme_control(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        js = (ROOT / "kioskctl/static/app.js").read_text()
        self.assertIn('id="browserColorScheme"', html)
        self.assertIn('id="applyBrowserTheme"', html)
        self.assertIn("$('currentUrl').title=fullUrl", js)
        self.assertIn("browser/color-scheme", js)

    def test_homeassistant_exposes_browser_theme_select(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["plugins"]["homeassistant"]["enabled"] = True
        mqtt = FakeMQTT()
        plugin = HomeAssistantPlugin(cfg, mqtt, EventBus(), lambda: {"browser_experience": {"color_scheme": "auto"}}, "0.5.2")
        entities = plugin._entities()
        self.assertIn("color_scheme", entities)
        component, entity = entities["color_scheme"]
        self.assertEqual(component, "select")
        self.assertEqual(entity["options"], ["auto", "light", "dark"])

    def test_version_046_is_synchronized(self):
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
