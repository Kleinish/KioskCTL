import tempfile
import unittest
from pathlib import Path

from kioskctl.browser import build_browser_command, browser_runtime_script
from kioskctl.config import DEFAULT_CONFIG, load_config

ROOT = Path(__file__).resolve().parents[1]


class V048FeatureTests(unittest.TestCase):
    def test_dark_mode_uses_persistent_chromium_flags(self):
        cfg = {**DEFAULT_CONFIG, "browser": {**DEFAULT_CONFIG["browser"], "color_scheme": "dark", "url": "https://example.com"}}
        with tempfile.TemporaryDirectory() as td:
            cfg["system"] = {**DEFAULT_CONFIG["system"], "kiosk_user": "root"}
            cfg["browser"]["user_data_dir"] = td
            cmd = build_browser_command(cfg)
        self.assertIn("--force-dark-mode", cmd)
        enabled = next(x for x in cmd if x.startswith("--enable-features="))
        self.assertIn("WebContentsForceDark", enabled)

    def test_runtime_cursor_starts_hidden_and_filters_touch_generated_mouse(self):
        js = browser_runtime_script(DEFAULT_CONFIG)
        self.assertIn("hideCursor();", js)
        self.assertIn("touchSeenUntil", js)
        self.assertIn("firesTouchEvents", js)

    def test_v5_config_migrates_to_v6_screensaver_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.yaml"
            p.write_text("version: 5\ndevice:\n  name: kiosk\n")
            cfg = load_config(p)
        self.assertEqual(cfg["version"], 10)
        self.assertIn("screensaver", cfg)
        self.assertEqual(cfg["screensaver"]["fit"], "contain")
        self.assertEqual(cfg["screensaver"]["after_seconds"], 120)

    def test_webui_groups_plugins_and_diagnostics(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        self.assertIn('data-settings-target="plugins"', html)
        self.assertIn('data-settings-pane="plugins"', html)
        self.assertNotIn('data-view-target="plugins"', html)
        self.assertNotIn('data-view-target="diagnostics"', html)
        self.assertIn('id="dashboardPower"', html)
        self.assertIn('id="screensaverFiles"', html)
        self.assertIn('id="diagnostics"', html)

    def test_screensaver_api_and_local_page_exist(self):
        main = (ROOT / "kioskctl/main.py").read_text()
        self.assertIn('@app.get("/screensaver"', main)
        self.assertIn('@app.post("/api/screensaver/images"', main)
        self.assertIn('@app.post("/api/screensaver/preview"', main)
        self.assertIn('MAX_SCREENSAVER_IMAGE_BYTES', main)


if __name__ == "__main__":
    unittest.main()
