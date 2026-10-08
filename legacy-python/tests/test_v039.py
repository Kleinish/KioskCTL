import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.config import DEFAULT_CONFIG
from kioskctl.platform import install_touch_transform, touch_calibration_matrix
import kioskctl.main as main

ROOT = Path(__file__).resolve().parents[1]


class V039RegressionTests(unittest.TestCase):
    def test_touch_rotation_matrices(self):
        self.assertEqual(touch_calibration_matrix('normal'), '1 0 0 0 1 0')
        self.assertEqual(touch_calibration_matrix('180'), '-1 0 1 0 -1 1')
        self.assertEqual(touch_calibration_matrix('90'), '0 -1 1 1 0 0')
        self.assertEqual(touch_calibration_matrix('270'), '0 1 0 -1 0 1')

    def test_touch_rotation_enabled_by_default(self):
        self.assertTrue(DEFAULT_CONFIG['input']['rotate_touch_with_display'])

    def test_touch_rule_written_for_180(self):
        cfg = {
            'display': {'transform': '180'},
            'input': {'rotate_touch_with_display': True},
        }
        with tempfile.TemporaryDirectory() as td:
            rule = Path(td) / '99-kioskctl-touch.rules'
            with patch('kioskctl.platform.TOUCH_RULE_PATH', rule), \
                 patch('kioskctl.platform.os.geteuid', return_value=0), \
                 patch('kioskctl.platform.shutil.which', return_value=None), \
                 patch('kioskctl.platform.input_devices', return_value=[]):
                result = install_touch_transform(cfg, reload_rules=False)
            self.assertIn('LIBINPUT_CALIBRATION_MATRIX', rule.read_text())
            self.assertIn('-1 0 1 0 -1 1', rule.read_text())
            self.assertTrue(result['rule_installed'])

    def test_fresh_install_keeps_stateless_service_identity(self):
        install = (ROOT / 'install.sh').read_text()
        uninstall = (ROOT / 'uninstall.sh').read_text()
        self.assertIn('"$SCRIPT_DIR/uninstall.sh" --purge --yes --keep-user', install)
        self.assertIn('--keep-user', uninstall)
        self.assertIn('user-runtime-dir@${KIOSK_UID}.service', uninstall)
        self.assertIn('userdel -f -r kioskctl', uninstall)

    def test_mqtt_reload_uses_action_helper_not_route_forward_reference(self):
        source = (ROOT / 'kioskctl/main.py').read_text()
        block = source[source.index('def mqtt_command'):source.index('mqtt_bridge = MQTTBridge')]
        self.assertIn('_browser_reload_action()', block)
        self.assertNotIn('browser_reload()', block)
        with patch('kioskctl.main._browser_reload_action') as action:
            main.mqtt_command('reload', 'PRESS')
        action.assert_called_once_with()

    def test_side_navigation_ships(self):
        html = (ROOT / 'kioskctl/static/index.html').read_text()
        js = (ROOT / 'kioskctl/static/app.js').read_text()
        self.assertIn('data-view-target="dashboard"', html)
        self.assertIn('data-view-target="settings"', html)
        self.assertIn('Display &amp; Input', html)
        self.assertIn('function setView', js)

    def test_update_errors_are_sanitized(self):
        main = (ROOT / 'kioskctl/main.py').read_text()
        self.assertIn('Update failed. Check kioskctl-agent logs for details.', main)
        self.assertIn('logger.error("Configured update failed', main)

    def test_version(self):
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / 'install.sh').read_text())
        self.assertIn('version = "0.5.2"', (ROOT / 'pyproject.toml').read_text())
        self.assertIn('v0.5.2', (ROOT / 'kioskctl/static/index.html').read_text())


if __name__ == '__main__':
    unittest.main()
