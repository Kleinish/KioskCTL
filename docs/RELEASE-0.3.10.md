# kioskctl 0.3.10

This hardware-matrix maintenance release keeps the 0.3.9 sidebar and proven Cage/logind/OpenRC session architecture while fixing the next physical-laptop findings.

## Fixed

- Web-admin IP detection no longer depends on `hostname -I`; it prefers the IPv4 source selected by `ip route` and falls back to a global IPv4 address. This fixes the `<kiosk-ip>` install summary on Arch and Alpine.
- Chromium remote key injection now sends DOM code and virtual-key metadata. Enter once again submits/activates focused controls, Backspace performs `deleteBackward`, and Tab/Escape/navigation keys retain physical-key behavior.
- Non-default display settings get a second output reinitialize after Chromium maps. This automates the manual **Rotate -> Reinitialize** workaround observed on Arch and Debian and keeps rotation/scale/mode settings across **Restart browser**.
- The managed touch calibration rule now targets `event*` touchscreen nodes explicitly. Touchscreen event devices are retriggered after a rule change and diagnostics expose the matrix actually present in the udev database.
- Alpine installs `eudev`, which provides `udevadm`, so runtime libinput calibration rules can be reloaded instead of only written to disk.

## Test focus

1. Fresh install on all distro targets and confirm the printed Web admin address contains the device IPv4.
2. Rotate to 180 degrees on Arch/Debian and confirm no separate Reinitialize click is needed.
3. Restart the browser while rotated and confirm the transform returns automatically.
4. On Alpine, rotate with **Rotate physical touchscreen coordinates with the display** enabled and verify physical touch follows the visible controls.
5. Verify Enter, Tab, Escape and Backspace in a focused browser form.
