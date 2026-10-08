import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from kioskctl.config import load_config
from kioskctl.events import EventBus
from kioskctl.plugins.homeassistant import HomeAssistantPlugin

ROOT = Path(__file__).resolve().parents[1]


class FakeMQTT:
    def __init__(self):
        self.device_id = "archkiosk"
        self.base = "kioskctl/archkiosk"
        self.connected = True
        self.connect_listeners = []
        self.subscriptions = {}
        self.published = []

    def add_connect_listener(self, cb):
        self.connect_listeners.append(cb)

    def subscribe(self, topic, cb):
        self.subscriptions[topic] = cb

    def publish_json(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))
        return True

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))
        return True


class V040PluginTests(unittest.TestCase):
    def test_v3_home_assistant_mqtt_settings_migrate_to_plugin(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.yaml"
            p.write_text(
                "version: 3\n"
                "device:\n  name: archkiosk\n"
                "mqtt:\n"
                "  enabled: true\n"
                "  host: 10.3.210.29\n"
                "  home_assistant_discovery: true\n"
                "  discovery_prefix: homeassistant\n"
            )
            cfg = load_config(p)
        self.assertEqual(cfg["version"], 10)
        self.assertTrue(cfg["mqtt"]["enabled"])
        self.assertTrue(cfg["plugins"]["homeassistant"]["enabled"])
        self.assertEqual(cfg["plugins"]["homeassistant"]["discovery_prefix"], "homeassistant")
        self.assertNotIn("home_assistant_discovery", cfg["mqtt"])

    def test_homeassistant_plugin_preserves_existing_entity_ids_and_expands_entities(self):
        cfg = load_config(Path("/definitely/not/present"))
        cfg["device"]["name"] = "archkiosk"
        cfg["plugins"]["homeassistant"]["enabled"] = True
        mqtt = FakeMQTT()
        plugin = HomeAssistantPlugin(cfg, mqtt, EventBus(), MagicMock(return_value={}), "0.5.2")
        plugin.start()
        result = plugin.publish_discovery()
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["entities"], 12)
        topics = {topic for topic, payload, retain in mqtt.published}
        self.assertIn("homeassistant/sensor/kioskctl_archkiosk/status/config", topics)
        self.assertIn("homeassistant/button/kioskctl_archkiosk/reboot/config", topics)
        self.assertIn("homeassistant/button/kioskctl_archkiosk/reload/config", topics)
        self.assertIn("homeassistant/number/kioskctl_archkiosk/volume/config", topics)
        self.assertIn("homeassistant/select/kioskctl_archkiosk/rotation/config", topics)
        status_payload = next(payload for topic, payload, retain in mqtt.published if topic.endswith("/status/config"))
        self.assertNotIn("device_class", status_payload)  # fixes the old enum discovery issue

    def test_homeassistant_republishes_on_birth_message(self):
        cfg = load_config(Path("/definitely/not/present"))
        cfg["plugins"]["homeassistant"]["enabled"] = True
        mqtt = FakeMQTT()
        plugin = HomeAssistantPlugin(cfg, mqtt, EventBus(), MagicMock(return_value={}), "0.5.2")
        plugin.start()
        mqtt.published.clear()
        plugin._on_homeassistant_status("homeassistant/status", "online")
        self.assertTrue(mqtt.published)

    def test_plugin_ui_and_transport_are_separate(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        main = (ROOT / "kioskctl/main.py").read_text()
        mqtt = (ROOT / "kioskctl/mqtt.py").read_text()
        self.assertIn('data-settings-target="plugins"', html)
        self.assertIn('data-settings-pane="plugins"', html)
        self.assertNotIn('data-view-target="plugins"', html)
        self.assertIn("MQTT transport", html)
        self.assertIn("Home Assistant", html)
        self.assertIn('/api/plugins/homeassistant/republish', main)
        self.assertNotIn('_publish_ha_discovery', mqtt)

    def test_version(self):
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / 'install.sh').read_text())
        self.assertIn('version = "0.5.2"', (ROOT / 'pyproject.toml').read_text())
        self.assertIn('v0.5.2', (ROOT / 'kioskctl/static/index.html').read_text())


if __name__ == '__main__':
    unittest.main()
