import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.config import DEFAULT_CONFIG
from kioskctl.plugins.immich import ImmichPlugin

ROOT = Path(__file__).resolve().parents[1]


class _Headers:
    def __init__(self, content_type="image/jpeg"):
        self._content_type = content_type
    def get_content_type(self):
        return self._content_type


class _Response:
    def __init__(self, payload=b"bytes", content_type="image/jpeg"):
        self.payload = payload
        self.headers = _Headers(content_type)
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False
    def read(self, _limit=-1): return self.payload


class V052RegressionTests(unittest.TestCase):
    def _plugin(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["plugins"]["immich"].update({
            "installed": True, "enabled": True,
            "server_url": "http://immich.test:2283", "api_key": "secret",
        })
        return ImmichPlugin(cfg)

    def test_browser_native_asset_uses_original(self):
        plugin = self._plugin()
        asset_id = "01234567-89ab-cdef-0123-456789abcdef"
        plugin._assets = [{"id": asset_id, "file_name": "x.jpg", "original_mime_type": "image/jpeg"}]
        seen = {}
        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            return _Response()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            plugin.proxy_image(asset_id)
        self.assertTrue(seen["url"].endswith(f"/api/assets/{asset_id}/original"))

    def test_heic_uses_fullsize_fallback(self):
        plugin = self._plugin()
        asset_id = "01234567-89ab-cdef-0123-456789abcdef"
        plugin._assets = [{"id": asset_id, "file_name": "x.heic", "original_mime_type": "image/heic"}]
        seen = {}
        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            return _Response()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            plugin.proxy_image(asset_id)
        self.assertIn("/thumbnail?size=fullsize", seen["url"])

    def test_immich_screen_hides_loading_overlay_and_uses_natural_dimensions(self):
        source = (ROOT / "kioskctl/main.py").read_text()
        self.assertIn("#slide[hidden],#empty[hidden]{{display:none!important}}", source)
        self.assertIn("img.naturalWidth", source)
        self.assertIn("Math.min(vw/iw,vh/ih)", source)
        self.assertIn("Math.max(vw/iw,vh/ih)", source)

    def test_preview_refreshes_active_screensaver(self):
        source = (ROOT / "kioskctl/idle.py").read_text()
        self.assertIn('self._hide_screensaver(cfg, "preview-refresh")', source)

    def test_version_052_is_synchronized(self):
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / "install.sh").read_text())
        self.assertIn('__version__ = "0.5.2"', (ROOT / "kioskctl/__init__.py").read_text())
        self.assertIn('APP_VERSION = "0.5.2"', (ROOT / "kioskctl/main.py").read_text())
        self.assertIn('version = "0.5.2"', (ROOT / "pyproject.toml").read_text())
        html = (ROOT / "kioskctl/static/index.html").read_text()
        self.assertIn("v0.5.2", html)
        self.assertIn("app.js?v=0.5.2", html)
        self.assertIn("style.css?v=0.5.2", html)
        self.assertTrue((ROOT / "docs/RELEASE-0.5.2.md").is_file())


if __name__ == "__main__":
    unittest.main()
