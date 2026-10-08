import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from kioskctl.platform import WaylandTools


CFG = {
    "system": {"kiosk_user": "kioskctl", "runtime_dir": "/run/kioskctl", "wayland_display": "auto"},
    "display": {"output": "auto"},
    "audio": {"provider": "auto"},
}


class V036UiAndSessionStateTests(unittest.TestCase):
    def test_runtime_candidates_include_legacy_and_openrc_runtime(self):
        tools = WaylandTools(CFG)
        with patch("kioskctl.platform.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=1000)):
            values = tools._runtime_dirs()
        self.assertIn("/run/kioskctl", values)
        self.assertIn("/run/kioskctl-user", values)
        self.assertIn("/run/user/1000", values)

    def test_display_snapshot_is_used_when_live_probe_is_unavailable(self):
        tools = WaylandTools(CFG)
        expected = [{"name": "eDP-1", "enabled": True, "modes": []}]
        with patch.object(tools, "raw_wlr_randr", return_value=""), patch.object(
            tools,
            "_display_snapshot",
            return_value={
                "runtime_dir": "/run/kioskctl-user",
                "wayland_display": "wayland-0",
                "outputs": expected,
            },
        ):
            self.assertEqual(tools.output_details(), expected)
            self.assertEqual(tools.display_source(), "session-snapshot")
            self.assertEqual(tools._detected_runtime_dir, "/run/kioskctl-user")
            self.assertEqual(tools._detected_wayland_display, "wayland-0")

    def test_geometry_can_reuse_already_probed_outputs(self):
        tools = WaylandTools(CFG)
        details = [{
            "name": "eDP-1",
            "enabled": True,
            "current_mode": {"width": 1920, "height": 1080},
            "scale": 1.0,
            "transform": "normal",
        }]
        viewport = {"screenWidth": 1920, "screenHeight": 1080}
        with patch.object(tools, "output_details", side_effect=AssertionError("must not re-probe")):
            result = tools.geometry_status(viewport, details)
        self.assertTrue(result["matched"])

    def test_session_helper_publishes_display_snapshot(self):
        text = Path(__file__).parents[1].joinpath("kioskctl/display_fixup.py").read_text()
        self.assertIn("kioskctl-display.json", text)
        self.assertIn("state published", text)

    def test_web_assets_are_version_busted_and_no_store(self):
        root = Path(__file__).parents[1]
        html = root.joinpath("kioskctl/static/index.html").read_text()
        main = root.joinpath("kioskctl/main.py").read_text()
        js = root.joinpath("kioskctl/static/app.js").read_text()
        self.assertIn("app.js?v=0.5.2", html)
        self.assertIn("style.css?v=0.5.2", html)
        self.assertIn("Cache-Control", main)
        self.assertIn("cache:'no-store'", js)

    def test_ui_renders_hardware_and_display_independently(self):
        js = Path(__file__).parents[1].joinpath("kioskctl/static/app.js").read_text()
        self.assertIn("UI hardware render", js)
        self.assertIn("UI display render", js)
        self.assertIn("setInterval(()=>{if(token)refreshDiagnostics();},30000)", js)


if __name__ == "__main__":
    unittest.main()
