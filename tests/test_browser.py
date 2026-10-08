import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kioskctl.browser import browser_provider, build_browser_command, prepare_browser_profile, resolved_user_data_dir
from kioskctl.config import DEFAULT_CONFIG


class BrowserCommandTests(unittest.TestCase):
    @patch('kioskctl.browser.chromium_executable', return_value='/usr/bin/chromium')
    @patch('kioskctl.browser.prepare_browser_profile', return_value=Path('/tmp/profile'))
    def test_kiosk_and_local_devtools(self, profile, executable):
        cfg = {**DEFAULT_CONFIG, 'browser': {**DEFAULT_CONFIG['browser'], 'url': 'https://example.org'}}
        cmd = build_browser_command(cfg)
        self.assertIn('--kiosk', cmd)
        self.assertIn('--remote-debugging-address=127.0.0.1', cmd)
        self.assertIn('--disable-notifications', cmd)
        self.assertEqual(cmd[-1], 'https://example.org')

    @patch('kioskctl.browser.chromium_executable', return_value='/snap/bin/chromium')
    def test_snap_provider_detection(self, executable):
        self.assertEqual(browser_provider(DEFAULT_CONFIG), 'chromium-snap')

    @patch('kioskctl.browser.chromium_executable', return_value='/snap/bin/chromium')
    @patch('kioskctl.browser.kiosk_home', return_value=Path('/home/kioskctl'))
    def test_snap_profile_is_under_home_snap_tree(self, home, executable):
        profile = resolved_user_data_dir(DEFAULT_CONFIG)
        self.assertEqual(profile, Path('/home/kioskctl/snap/chromium/common/kioskctl-profile'))

    @patch('kioskctl.browser.chromium_executable', return_value='/usr/bin/chromium')
    def test_profile_preferences_disable_prompts(self, executable):
        with tempfile.TemporaryDirectory() as td:
            cfg = {**DEFAULT_CONFIG, 'browser': {**DEFAULT_CONFIG['browser'], 'user_data_dir': td}}
            prepare_browser_profile(cfg)
            prefs = json.loads((Path(td) / 'Default' / 'Preferences').read_text())
            self.assertFalse(prefs['profile']['password_manager_enabled'])
            self.assertEqual(prefs['profile']['default_content_setting_values']['notifications'], 2)
            self.assertFalse(prefs['autofill']['profile_enabled'])


if __name__ == '__main__':
    unittest.main()
