import argparse
import unittest
from pathlib import Path
from unittest.mock import patch

import kioskctl.cli as cli


ROOT = Path(__file__).parents[1]


class V037FreshInstallTests(unittest.TestCase):
    def test_release_ships_top_level_uninstaller(self):
        text = (ROOT / "uninstall.sh").read_text()
        self.assertIn("--purge", text)
        self.assertIn("--yes", text)
        self.assertIn("/etc/kioskctl", text)
        self.assertIn("/home/kioskctl", text)
        self.assertIn("/etc/chromium/policies/managed/kioskctl.json", text)

    def test_purge_retains_shared_os_packages_and_admin_account(self):
        text = (ROOT / "uninstall.sh").read_text()
        # The purge script must not invoke distro package removal commands.
        self.assertNotIn("apt-get remove", text)
        self.assertNotIn("apt remove", text)
        self.assertNotIn("dnf remove", text)
        self.assertNotIn("pacman -R", text)
        self.assertNotIn("apk del", text)
        # User deletion is hard-scoped to the dedicated account.
        self.assertIn("userdel -r kioskctl", text)
        self.assertNotIn("userdel -r kiosk\n", text)

    def test_systemd_purge_restores_normal_getty(self):
        text = (ROOT / "uninstall.sh").read_text()
        self.assertIn("systemctl stop getty@tty1.service", text)
        self.assertIn("kioskctl-autologin.conf", text)
        self.assertIn("systemctl daemon-reload", text)
        self.assertIn("systemctl start getty@tty1.service", text)

    def test_installer_has_fresh_mode(self):
        text = (ROOT / "install.sh").read_text()
        self.assertIn("--fresh", text)
        self.assertIn('"$SCRIPT_DIR/uninstall.sh" --purge --yes', text)
        self.assertIn("EXISTING_CONFIG=0", text)
        self.assertIn("default-disabled (fresh install)", text)

    def test_fresh_dry_run_is_documented_non_destructive(self):
        text = (ROOT / "install.sh").read_text()
        dry_run_pos = text.index('if [[ $DRY_RUN -eq 1 ]]; then exit 0; fi')
        purge_pos = text.index('"$SCRIPT_DIR/uninstall.sh" --purge --yes')
        self.assertLess(dry_run_pos, purge_pos)

    def test_cli_exposes_uninstall(self):
        text = (ROOT / "kioskctl/cli.py").read_text()
        self.assertIn("sub.add_parser('uninstall'", text)
        self.assertIn("--purge", text)
        self.assertIn("--yes", text)
        self.assertIn("/opt/kioskctl/uninstall.sh", text)

    def test_cli_dispatches_purge_to_installed_uninstaller(self):
        args = argparse.Namespace(command="uninstall", purge=True, yes=True)
        with patch.object(Path, "exists", return_value=True), patch("kioskctl.cli.subprocess.run") as run:
            cli._dispatch(args)
        run.assert_called_once_with(
            ["/opt/kioskctl/uninstall.sh", "--purge", "--yes"], check=True
        )

    def test_versions_are_037(self):
        self.assertIn('0.5.2', (ROOT / 'pyproject.toml').read_text())
        self.assertIn('v0.5.2', (ROOT / 'kioskctl/static/index.html').read_text())
        self.assertIn('KIOSKCTL_VERSION="0.5.2"', (ROOT / 'install.sh').read_text())


if __name__ == "__main__":
    unittest.main()
