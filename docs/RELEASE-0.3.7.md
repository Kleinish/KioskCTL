# kioskctl 0.3.7

Reproducible fresh-install / uninstall release.

## Added

- `./install.sh --fresh` purges kioskctl-owned state before installation.
- Top-level `uninstall.sh` in every release.
- Installed canonical uninstaller at `/opt/kioskctl/uninstall.sh` and `/usr/local/bin/kioskctl-uninstall`.
- `kioskctl uninstall` CLI command with `--purge` and `--yes`.
- Non-interactive purge mode for multi-exec development testing.

## Purge boundary

`--purge` removes kioskctl-owned application files, services, config/data, runtime state, logs, browser profile/home, managed Chromium policy, and the dedicated `kioskctl` account. It restores the normal tty1 getty on systemd systems.

It intentionally retains distro packages including Chromium, Cage, PipeWire/PulseAudio/ALSA tools, `wlr-randr`, `brightnessctl`, `seatd`, Python, and other shared system packages. It never removes or modifies the normal administrator account.

## Recommended development cycle

```bash
sudo ./install.sh --fresh --enable-kiosk --url "https://example.com"
sleep 10
sudo /opt/kioskctl/scripts/matrix-smoke.sh
```

This gives each pre-1.0 hardware test the same kioskctl starting state while leaving the OS/package layer stable.

No Cage/logind/OpenRC graphical startup behavior was otherwise changed in 0.3.7.
