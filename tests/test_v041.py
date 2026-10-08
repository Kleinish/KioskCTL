import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class V041UiRegressionTests(unittest.TestCase):
    def test_plugin_forms_are_dirty_aware(self):
        js = (ROOT / "kioskctl/static/app.js").read_text()
        self.assertIn("let mqttFormDirty = false", js)
        self.assertIn("let haFormDirty = false", js)
        self.assertIn("!mqttFormDirty && !formHasFocus(mqttFormIds)", js)
        self.assertIn("!haFormDirty && !formHasFocus(haFormIds)", js)
        self.assertIn("mqttFormDirty=true", js)
        self.assertIn("haFormDirty=true", js)
        self.assertIn("mqttFormDirty=false", js)
        self.assertIn("haFormDirty=false", js)

    def test_version_041_is_synchronized(self):
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / "install.sh").read_text())
        self.assertIn('__version__ = "0.5.2"', (ROOT / "kioskctl/__init__.py").read_text())
        self.assertIn('APP_VERSION = "0.5.2"', (ROOT / "kioskctl/main.py").read_text())
        self.assertIn('version = "0.5.2"', (ROOT / "pyproject.toml").read_text())
        html = (ROOT / "kioskctl/static/index.html").read_text()
        self.assertIn('v0.5.2', html)
        self.assertIn('app.js?v=0.5.2', html)


if __name__ == '__main__':
    unittest.main()
