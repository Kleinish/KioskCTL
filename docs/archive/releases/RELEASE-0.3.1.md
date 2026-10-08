# kioskctl 0.3.1

V0.3.1 is a reliability hotfix based on simultaneous Fedora, Debian, Arch, and Alpine hardware testing.

## Fixed

- Restores the proven V0.2 Cage→Chromium startup order; display initialization now runs beside the browser instead of delaying the first Wayland client.
- Fixes Wayland control helpers when they are already running as the dedicated `kioskctl` user (no nested `runuser`).
- Fedora no longer tries to `systemctl enable getty@tty1.service`; the getty instance is restarted/started after installing the autologin drop-in.
- Existing enabled installations are repaired with `enable-kiosk` during upgrade instead of only restarted.
- Empty `--name` values fall back to `hostname -s`.
- Diagnostics prefer real seat/TTY sessions over the user-manager session and include process/session-log tails.
- Alpine OpenRC browser service uses `supervise-daemon`, logs failures, and uses an explicit `openvt --` boundary.
- Multi-exec smoke output now includes getty/OpenRC state and graphical-session logs.

## Confirmed working from V0.3 field tests

- CPU temperature selection now chooses `coretemp` package temperature on the tested Intel laptops.
- Alpine ALSA fallback reports and controls volume.
