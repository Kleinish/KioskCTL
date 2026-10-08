# kioskctl 0.3.8

Fresh-install hardening after the 0.3.7 multi-distro purge test.

- Fixes a purge race where the systemd user manager could keep `kioskctl` alive,
  causing `userdel` to fail and leaving an account whose home had been deleted.
- `--fresh` now fails loudly if the dedicated account cannot be removed.
- Installer repairs/recreates `/home/kioskctl` if an interrupted older purge left
  a valid dedicated account without its home directory.
- Starts PipeWire/WirePlumber proactively for a fresh systemd kiosk user and
  briefly retries `wpctl` while the default sink appears.
- Fedora installs `pipewire-pulseaudio` and `xorg-x11-server-Xwayland`; the latter
  removes Cage's harmless-but-noisy missing-Xwayland error and supports future X11 clients.
- Installer-side `restorecon` is bounded to 10 seconds when `timeout` is available.
