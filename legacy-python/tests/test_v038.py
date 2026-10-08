import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class V038RegressionTests(unittest.TestCase):
    def test_installer_repairs_missing_home(self):
        text = (ROOT / 'install.sh').read_text()
        self.assertIn('install -d -m 0755 -o "$KIOSK_USER" -g "$KIOSK_USER" "$KIOSK_HOME"', text)

    def test_purge_terminates_user_and_verifies_deletion(self):
        text = (ROOT / 'uninstall.sh').read_text()
        self.assertIn('loginctl terminate-user kioskctl', text)
        self.assertIn('Unable to remove dedicated kioskctl user; purge is incomplete.', text)

    def test_fedora_has_xwayland_and_pipewire_pulse(self):
        text = (ROOT / 'install.sh').read_text()
        self.assertIn('xorg-x11-server-Xwayland', text)
        self.assertIn('pipewire-pulseaudio', text)

    def test_systemd_session_proactively_starts_audio(self):
        text = (ROOT / 'scripts/kioskctl-session').read_text()
        self.assertIn('systemctl --user start "$unit"', text)
        self.assertIn('wireplumber.service', text)

    def test_version(self):
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / 'install.sh').read_text())
        self.assertIn('version = "0.5.2"', (ROOT / 'pyproject.toml').read_text())

if __name__ == '__main__':
    unittest.main()
