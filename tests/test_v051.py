import copy
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.config import DEFAULT_CONFIG
from kioskctl.plugins.immich import ImmichPlugin

ROOT = Path(__file__).resolve().parents[1]


class _Headers:
    @staticmethod
    def get_content_type():
        return "image/jpeg"


class _Response:
    headers = _Headers()

    def __init__(self, payload=b"jpeg-bytes"):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _limit=-1):
        return self.payload


class V051RegressionTests(unittest.TestCase):
    def _plugin(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["plugins"]["immich"].update({
            "installed": True,
            "enabled": True,
            "server_url": "http://immich.test:2283",
            "api_key": "secret",
        })
        return ImmichPlugin(cfg)

    def test_immich_proxy_uses_fullsize_not_preview(self):
        plugin = self._plugin()
        plugin._assets = [{"id": "01234567-89ab-cdef-0123-456789abcdef", "file_name": "x.heic", "original_mime_type": "image/heic"}]
        seen = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["timeout"] = timeout
            return _Response()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            payload, content_type = plugin.proxy_image("01234567-89ab-cdef-0123-456789abcdef")

        self.assertEqual(payload, b"jpeg-bytes")
        self.assertEqual(content_type, "image/jpeg")
        self.assertIn("/thumbnail?size=fullsize", seen["url"])
        self.assertNotIn("size=preview", seen["url"])

    def test_immich_status_reports_fullsize_source(self):
        status = self._plugin().status()
        self.assertEqual(status["image_source"], "original-or-fullsize")

    def test_immich_connection_test_fetches_actual_fullsize_sample(self):
        plugin = self._plugin()
        plugin._request_json = lambda path, **kwargs: {"version": "2.0.0"}
        plugin.refresh_assets = lambda force=False: [{"id": "sample-asset", "file_name": "x.jpg"}]
        seen = {}

        def proxy(asset_id):
            seen["id"] = asset_id
            return b"image-bytes", "image/jpeg"

        plugin.proxy_image = proxy
        result = plugin.test_connection()
        self.assertEqual(seen["id"], "sample-asset")
        self.assertEqual(result["image_source"], "original-or-fullsize")
        self.assertEqual(result["sample_bytes"], len(b"image-bytes"))
        self.assertEqual(result["sample_content_type"], "image/jpeg")

    def test_immich_screen_uses_explicit_fit_geometry(self):
        source = (ROOT / "kioskctl/main.py").read_text()
        self.assertIn("img.naturalWidth", source)
        self.assertIn("Math.min(vw/iw,vh/ih)", source)
        self.assertIn("Math.max(vw/iw,vh/ih)", source)

    def test_release_051_notes_remain_packaged(self):
        self.assertTrue((ROOT / "docs/RELEASE-0.5.2.md").is_file())



if __name__ == "__main__":
    unittest.main()
