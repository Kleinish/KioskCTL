import unittest
from pathlib import Path

from kioskctl.runtime_monitor import _missing

ROOT = Path(__file__).resolve().parents[1]


class V045RegressionTests(unittest.TestCase):
    def test_runtime_monitor_is_session_scoped_and_cleaned_up(self):
        session = (ROOT / "scripts/kioskctl-session").read_text()
        self.assertIn("python -m kioskctl.runtime_monitor", session)
        self.assertIn("runtime_pid=$!", session)
        self.assertIn('kill "$fixup_pid" "$runtime_pid"', session)
        self.assertIn('wait "$runtime_pid"', session)

    def test_runtime_injection_uses_new_document_registration_and_immediate_mode(self):
        source = (ROOT / "kioskctl/browser.py").read_text()
        self.assertIn("Page.addScriptToEvaluateOnNewDocument", source)
        self.assertIn('"runImmediately": True', source)
        self.assertIn("runtime_feature_state", source)
        self.assertIn("runtime feature injection did not become active", source)

    def test_runtime_monitor_retries_expected_missing_overlays(self):
        features = {"pull_to_refresh": True, "edge_drawer": True, "onscreen_keyboard": True}
        self.assertEqual(_missing({"runtime": True, "pull": True, "edge": False, "keyboard": True}, features), ["edge"])
        self.assertEqual(_missing({"runtime": True, "pull": True, "edge": True, "keyboard": True}, features), [])

    def test_admin_theme_toggle_and_light_palette_are_present(self):
        html = (ROOT / "kioskctl/static/index.html").read_text()
        js = (ROOT / "kioskctl/static/app.js").read_text()
        css = (ROOT / "kioskctl/static/style.css").read_text()
        self.assertIn('id="themeToggle"', html)
        self.assertIn("kioskctl_theme", js)
        self.assertIn('data-theme="light"', css)

    def test_remote_controls_wrap_instead_of_overflowing_card(self):
        css = (ROOT / "kioskctl/static/style.css").read_text()
        self.assertIn(".remote-input{display:flex;flex-wrap:wrap", css)
        self.assertIn("overflow-x:hidden", css)
        self.assertIn(".section-head{flex-wrap:wrap}", css)

    def test_version_045_is_synchronized(self):
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
