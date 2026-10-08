import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.browser import DevTools
from kioskctl.display_fixup import _display_needs_post_start_reinitialize
from kioskctl.platform import install_touch_transform

ROOT = Path(__file__).resolve().parents[1]


class V0310RegressionTests(unittest.TestCase):
    def test_custom_rotation_requires_post_start_reinitialize(self):
        self.assertFalse(_display_needs_post_start_reinitialize({'display': {'transform': 'normal', 'scale': 1, 'mode': 'preferred', 'refresh_hz': 'auto'}}))
        self.assertTrue(_display_needs_post_start_reinitialize({'display': {'transform': '180', 'scale': 1, 'mode': 'preferred', 'refresh_hz': 'auto'}}))
        self.assertTrue(_display_needs_post_start_reinitialize({'display': {'transform': 'normal', 'scale': 1.25, 'mode': 'preferred', 'refresh_hz': 'auto'}}))

    def test_enter_dispatch_has_real_key_metadata(self):
        dt = DevTools(9222)
        calls = []
        with patch.object(dt, 'bring_to_front'), patch.object(dt, '_call', side_effect=lambda method, params=None: calls.append((method, params)) or {}):
            dt.key('Enter')
        key_calls = [params for method, params in calls if method == 'Input.dispatchKeyEvent']
        down = key_calls[0]
        up = key_calls[1]
        self.assertEqual(down['type'], 'keyDown')
        self.assertEqual(down['code'], 'Enter')
        self.assertEqual(down['windowsVirtualKeyCode'], 13)
        self.assertEqual(down['text'], '\r')
        self.assertEqual(up['type'], 'keyUp')

    def test_backspace_dispatches_delete_backward(self):
        dt = DevTools(9222)
        calls = []
        with patch.object(dt, 'bring_to_front'), patch.object(dt, '_call', side_effect=lambda method, params=None: calls.append((method, params)) or {}):
            dt.key('Backspace')
        key_calls = [params for method, params in calls if method == 'Input.dispatchKeyEvent']
        down = key_calls[0]
        self.assertEqual(down['type'], 'rawKeyDown')
        self.assertEqual(down['windowsVirtualKeyCode'], 8)
        self.assertIn('deleteBackward', down['commands'])

    def test_touch_rule_targets_event_devices(self):
        cfg = {'display': {'transform': '180'}, 'input': {'rotate_touch_with_display': True}}
        with tempfile.TemporaryDirectory() as td:
            rule = Path(td) / '99-kioskctl-touch.rules'
            with patch('kioskctl.platform.TOUCH_RULE_PATH', rule), \
                 patch('kioskctl.platform.os.geteuid', return_value=0), \
                 patch('kioskctl.platform.shutil.which', return_value=None), \
                 patch('kioskctl.platform.input_devices', return_value=[]):
                install_touch_transform(cfg, reload_rules=False)
            text = rule.read_text()
            self.assertIn('KERNEL=="event*"', text)
            self.assertIn('ENV{LIBINPUT_CALIBRATION_MATRIX}="-1 0 1 0 -1 1"', text)

    def test_installer_has_portable_ipv4_detection_and_alpine_udev(self):
        text = (ROOT / 'install.sh').read_text()
        self.assertIn('detect_primary_ipv4()', text)
        self.assertIn('ip -4 route get 1.1.1.1', text)
        self.assertIn('ip -o -4 addr show scope global', text)
        alpine = text[text.index('  alpine)'):text.index('    SESSION_PLAN=', text.index('  alpine)'))]
        self.assertIn('eudev', alpine)

    def test_display_apply_can_reinitialize_custom_config(self):
        text = (ROOT / 'kioskctl/main.py').read_text()
        self.assertIn('result = tools.reinitialize_display() if needs_reinitialize else tools.apply_display_config()', text)

    def test_version(self):
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / 'install.sh').read_text())
        self.assertIn('version = "0.5.2"', (ROOT / 'pyproject.toml').read_text())
        self.assertIn('v0.5.2', (ROOT / 'kioskctl/static/index.html').read_text())


if __name__ == '__main__':
    unittest.main()
