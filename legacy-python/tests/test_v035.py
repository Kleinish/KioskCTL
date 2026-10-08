import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.browser import DevTools
from kioskctl.config import load_config
from kioskctl.diagnostics import _seatd_socket_ok
from kioskctl.session import _restorecon


class V035HardeningTests(unittest.TestCase):
    def test_rejects_invalid_devtools_ports(self):
        for value in (0, 65536, -1, "not-a-port"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as td:
                p = Path(td) / "config.yaml"
                p.write_text(f"version: 3\nbrowser:\n  devtools_port: {value}\n")
                with self.assertRaises(ValueError):
                    load_config(p)

    def test_accepts_edge_port_values(self):
        for value in (1, 65535):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as td:
                p = Path(td) / "config.yaml"
                p.write_text(f"version: 3\nbrowser:\n  devtools_port: {value}\n")
                self.assertEqual(load_config(p)["browser"]["devtools_port"], value)

    def test_v2_config_migrates_to_current_schema(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.yaml"
            p.write_text("version: 2\ndevice:\n  name: old-kiosk\n")
            cfg = load_config(p)
            self.assertEqual(cfg["version"], 10)
            self.assertEqual(cfg["device"]["name"], "old-kiosk")
            self.assertIn("display", cfg)

    def test_future_config_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.yaml"
            p.write_text("version: 99\n")
            with self.assertRaisesRegex(ValueError, "newer than"):
                load_config(p)

    def test_seatd_regular_file_is_not_socket(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "seatd.sock"
            p.write_text("not a socket")
            self.assertFalse(_seatd_socket_ok(p))

    def test_seatd_unix_socket_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "seatd.sock"
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(p))
            try:
                self.assertTrue(_seatd_socket_ok(p))
            finally:
                sock.close()

    def test_restorecon_timeout_is_bounded(self):
        with patch("kioskctl.session.shutil.which", return_value="/usr/sbin/restorecon"), patch(
            "kioskctl.session.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="restorecon", timeout=10),
        ):
            with self.assertRaisesRegex(RuntimeError, "restorecon timed out"):
                _restorecon(Path("/tmp/example"))

    def test_devtools_constructor_validates_port(self):
        with self.assertRaises(ValueError):
            DevTools(0)

    def test_display_fixup_reports_devtools_timeout(self):
        text = Path(__file__).parents[1].joinpath("kioskctl/display_fixup.py").read_text()
        self.assertIn("browser DevTools did not become ready within 15 seconds", text)

    def test_cli_has_friendly_error_and_debug_escape_hatch(self):
        text = Path(__file__).parents[1].joinpath("kioskctl/cli.py").read_text()
        self.assertIn("kioskctl: error:", text)
        self.assertIn("KIOSKCTL_DEBUG", text)


if __name__ == "__main__":
    unittest.main()
