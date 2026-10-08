import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.browser import DevTools, managed_policy
from kioskctl.config import DEFAULT_CONFIG
from kioskctl.platform import WaylandTools


class V034RegressionTests(unittest.TestCase):
    def test_wayland_socket_auto_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            path = Path(td) / "wayland-7"
            sock.bind(str(path))
            try:
                cfg = {**DEFAULT_CONFIG, "system": {**DEFAULT_CONFIG["system"], "runtime_dir": td, "wayland_display": "auto"}}
                tools = WaylandTools(cfg)
                self.assertEqual(tools.wayland_display(), "wayland-7")
            finally:
                sock.close()

    def test_native_policy_blocks_prompts_by_default(self):
        policy = managed_policy(DEFAULT_CONFIG)
        self.assertFalse(policy["PasswordManagerEnabled"])
        self.assertEqual(policy["DefaultNotificationsSetting"], 2)
        self.assertFalse(policy["AutofillAddressEnabled"])
        self.assertFalse(policy["TranslateEnabled"])

    def test_remote_text_falls_back_to_key_events_for_iframe_focus(self):
        dt = DevTools(9222)
        calls = []
        focuses = [
            {"editable": False, "tag": "iframe"},
            {"editable": False, "tag": "iframe"},
        ]

        def fake_call(method, params=None):
            calls.append((method, params or {}))
            return {}

        with patch.object(dt, "bring_to_front"), patch.object(dt, "focus_info", side_effect=focuses), patch.object(dt, "_call", side_effect=fake_call):
            result = dt.insert_text("ab")

        chars = [params.get("text") for method, params in calls if method == "Input.dispatchKeyEvent"]
        self.assertEqual(chars, ["a", "b"])
        self.assertEqual(result["method"], "keyEvents")

    def test_geometry_matches_logical_output(self):
        cfg = {**DEFAULT_CONFIG, "display": {**DEFAULT_CONFIG["display"], "output": "auto"}}
        tools = WaylandTools(cfg)
        output = [{
            "name": "eDP-1",
            "enabled": True,
            "current_mode": {"width": 1920, "height": 1080, "refresh_hz": 60},
            "scale": 1.0,
            "transform": "normal",
        }]
        with patch.object(tools, "output_details", return_value=output):
            result = tools.geometry_status({"screenWidth": 1920, "screenHeight": 1080})
        self.assertTrue(result and result["matched"])


if __name__ == '__main__':
    unittest.main()
