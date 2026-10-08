import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class V042PluginSaveRegressionTests(unittest.TestCase):
    def test_mqtt_and_homeassistant_config_routes_bind_json_body(self):
        # 0.4.1 registered these routes before the Pydantic body classes existed.
        # With postponed annotations FastAPI treated `body` as a query parameter,
        # so Web UI POSTs returned 422 and appeared to do nothing.
        old = os.environ.get("KIOSKCTL_CONFIG")
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.yaml"
            os.environ["KIOSKCTL_CONFIG"] = str(cfg)
            sys.modules.pop("kioskctl.main", None)
            main = importlib.import_module("kioskctl.main")
            routes = {getattr(r, "path", ""): r for r in main.app.routes}
            for path in ("/api/mqtt/config", "/api/plugins/homeassistant/config"):
                route = routes[path]
                self.assertEqual([p.name for p in route.dependant.body_params], ["body"], path)
                self.assertNotIn("body", [p.name for p in route.dependant.query_params], path)
        sys.modules.pop("kioskctl.main", None)
        if old is None:
            os.environ.pop("KIOSKCTL_CONFIG", None)
        else:
            os.environ["KIOSKCTL_CONFIG"] = old

    def test_plugin_save_feedback_is_visible_on_plugin_page(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        js = (ROOT / "kioskctl/static/app.js").read_text()
        self.assertIn('id="mqttSaveStatus"', html)
        self.assertIn('id="haSaveStatus"', html)
        self.assertIn("Saving MQTT settings", js)
        self.assertIn("Save failed:", js)
        self.assertIn("published ${count} entities", js)

    def test_version_042_is_synchronized(self):
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / "install.sh").read_text())
        self.assertIn('__version__ = "0.5.2"', (ROOT / "kioskctl/__init__.py").read_text())
        self.assertIn('APP_VERSION = "0.5.2"', (ROOT / "kioskctl/main.py").read_text())
        self.assertIn('version = "0.5.2"', (ROOT / "pyproject.toml").read_text())
        html = (ROOT / "kioskctl/static/index.html").read_text()
        self.assertIn('v0.5.2', html)
        self.assertIn('app.js?v=0.5.2', html)


if __name__ == "__main__":
    unittest.main()
