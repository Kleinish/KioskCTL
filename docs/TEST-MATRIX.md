# V0.3 multi-exec hardware test matrix

The goal is to run the **same command sequence** on Ubuntu, Debian, Arch, Fedora, and Alpine and collect comparable JSON.

## Install / upgrade all hosts

From the extracted V0.3 directory on every host:

```bash
./install.sh --dry-run
sudo ./install.sh --url "https://example.com"
```

If V0.2 was already installed, the installer preserves its token and configuration by default.

## Pre-kiosk baseline

```bash
sudo kioskctl doctor --json
sudo kioskctl status
```

Expected: agent is healthy; kiosk may be disabled; browser/Wayland warnings are normal while disabled.

## Enable and settle

```bash
sudo kioskctl enable-kiosk
sleep 10
sudo kioskctl doctor --json
```

## Reinitialize display

```bash
sudo kioskctl reinitialize-display
sleep 3
sudo kioskctl status
```

This is particularly important on the Arch laptop that previously required Screen Off → Screen On before the geometry and remote text path corrected themselves.

## One-command collector

```bash
sudo /opt/kioskctl/scripts/matrix-smoke.sh
```

## Web UI checks

On every host verify:

1. Physical display fills the selected resolution.
2. Password-save prompt does not appear.
3. Notification permission prompt is blocked by default.
4. Screenshot looks like the physical page viewport.
5. Clicking screenshot focuses the expected control.
6. Focus indicator updates.
7. Send text works without first cycling display power.
8. Back / Reload / Restart browser work.
9. URL change works and survives reboot.
10. Screen Off / Screen On work.
11. Reinitialize produces the correct geometry.
12. Brightness works where a backlight device exists.
13. Audio provider is reported and volume changes where hardware exposes a mixer/sink.
14. CPU temperature sensor ID is plausible.
15. Reboot returns to kiosk mode when enabled.
16. Disable kiosk restores the recovery console.

## Useful comparison fields

From `doctor --json`, compare:

```text
distro
init_system
session
browser.provider
browser.version
browser.viewport
display.outputs[].current_mode
display.outputs[].preferred_mode
display.outputs[].scale
display.outputs[].transform
audio.provider
audio.volume
temperature_sensors[].id
temperature_sensors[].score
checks[]
```

If one platform behaves differently, send the JSON from that host plus one known-good host. That gives a provider-level comparison without requiring a different command set.
