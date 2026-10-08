# Arch Linux notes — kioskctl 0.3

Arch is a supported V0.3 hardware-test target using native repository Chromium, Cage, wlroots tooling, PipeWire/WirePlumber and ALSA fallback.

V0.3 specifically addresses a startup modeset race seen during Arch testing where the physical display initially showed only part of the viewport. Cage now starts first, kioskctl waits for the Wayland output, explicitly applies the preferred/configured mode, then starts Chromium.

Install/upgrade:

```bash
./install.sh --dry-run
sudo ./install.sh --url "https://example.com"
```

Diagnostics:

```bash
sudo kioskctl doctor --json
journalctl -t kioskctl-session -n 200 --no-pager
```

If geometry is still wrong:

```bash
sudo kioskctl reinitialize-display
```
