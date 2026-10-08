import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.diagnostics import _systemd_session


class HotfixRegressionTests(unittest.TestCase):
    def test_systemd_session_prefers_seat(self):
        cfg = {"system": {"kiosk_user": "kioskctl"}}
        sessions = [
            {"session":"1","uid":"1001","user":"kioskctl","seat":"-","leader":"10","class":"manager","tty":"-"},
            {"session":"2","uid":"1001","user":"kioskctl","seat":"seat0","leader":"20","class":"user","tty":"tty1"},
        ]
        with patch("kioskctl.diagnostics._systemd_sessions", return_value=sessions):
            self.assertEqual(_systemd_session(cfg)["seat"], "seat0")

    def test_launcher_uses_portable_cage_flags(self):
        text = Path(__file__).parents[1].joinpath("kioskctl/launcher.py").read_text()
        self.assertIn('["cage", "-d", "--"', text)
        self.assertNotIn('"-D"', text)

    def test_session_does_not_preseed_wayland_display(self):
        text = Path(__file__).parents[1].joinpath("scripts/kioskctl-session").read_text()
        self.assertIn("unset WAYLAND_DISPLAY", text)
        self.assertNotIn('export WAYLAND_DISPLAY=', text)

    def test_versions_are_synchronized(self):
        root = Path(__file__).parents[1]
        self.assertIn('__version__ = "0.5.2"', (root / "kioskctl/__init__.py").read_text())
        self.assertIn('APP_VERSION = "0.5.2"', (root / "kioskctl/main.py").read_text())
        self.assertIn('version = "0.5.2"', (root / "pyproject.toml").read_text())
        self.assertIn('v0.5.2', (root / "kioskctl/static/index.html").read_text())

    def test_fedora_dropin_install_does_not_use_copy2(self):
        text = Path(__file__).parents[1].joinpath("kioskctl/session.py").read_text()
        self.assertIn("_install_systemd_override", text)
        self.assertNotIn("shutil.copy2(TEMPLATE_PATH, OVERRIDE_PATH)", text)
        self.assertIn("restorecon", text)

    def test_systemd_getty_reload_is_verified(self):
        text = Path(__file__).parents[1].joinpath("kioskctl/session.py").read_text()
        self.assertIn("_getty_has_autologin", text)
        self.assertIn("daemon-reexec", text)
        self.assertIn("--autologin kioskctl", text)


if __name__ == '__main__':
    unittest.main()
