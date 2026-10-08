import tempfile
import unittest
from pathlib import Path

from kioskctl.config import load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_defaults_merge(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.yaml"
            p.write_text("device:\n  name: test-unit\nbrowser:\n  url: https://example.org\n")
            cfg = load_config(p)
            self.assertEqual(cfg["device"]["name"], "test-unit")
            self.assertEqual(cfg["browser"]["url"], "https://example.org")
            self.assertEqual(cfg["admin"]["port"], 2324)
            self.assertEqual(cfg["version"], 10)
            self.assertEqual(cfg["display"]["mode"], "preferred")

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.yaml"
            cfg = load_config(p)
            cfg["device"]["name"] = "round-trip"
            save_config(cfg, p)
            self.assertEqual(load_config(p)["device"]["name"], "round-trip")


if __name__ == "__main__":
    unittest.main()
