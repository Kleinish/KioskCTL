# kioskctl 0.3.3

Fedora-specific hotfix based on Fedora 44 multi-platform testing.

## Fixed

- Install the `getty@tty1` autologin drop-in without copying source SELinux xattrs.
- Run `restorecon` on the systemd drop-in and session entry points where available.
- Verify systemd loaded `--autologin kioskctl` before restarting tty1.
- Use `systemctl daemon-reexec` only as a fallback when Fedora still has the old getty definition cached.
- Fail with a focused diagnostic instead of reporting kiosk mode enabled when the drop-in was not actually loaded.

No changes were made to the working Debian, Arch, or Alpine graphical startup path.
