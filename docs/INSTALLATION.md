# Installation

Supported systems are Linux x86_64/aarch64 with systemd or OpenRC. Rust 1.88+, a C compiler, and standard development headers are needed to build. Chromium, Cage (or another compositor), `wlr-randr`, `curl`, udev, and PipeWire/PulseAudio tools support runtime features.

```bash
cargo test
cargo build --release
sudo ./install.sh
```

To install a CI-built binary: `KIOSKCTL_BINARY=/path/to/kioskctl sudo -E ./install.sh`.

The installer creates the `kioskctl` account/group, program/data/config directories, services, and `/usr/local/bin/kioskctl`. Existing program and config trees get timestamped backups.

On systemd systems, the agent and browser services each create their own
runtime directory at startup. Do not manually create `/run/user/<uid>` for the
`kioskctl` system account; its graphical session uses `/run/kioskctl-user`.

For a physical DRM/Wayland kiosk, install and start SeatD before the browser
service. The installer adds `kioskctl` to any existing `seat`, `video`,
`render`, `input`, and `audio` groups.

```bash
# Debian/Ubuntu
sudo apt install seatd
sudo systemctl enable --now seatd

# Fedora
sudo dnf install seatd
sudo systemctl enable --now seatd

# Arch
sudo pacman -S seatd
sudo systemctl enable --now seatd
```

Verify with:

```bash
sudo kioskctl --config /etc/kioskctl/config.yaml check-config
sudo kioskctl doctor
systemctl status kioskctl-agent
curl http://127.0.0.1:2324/api/health
```

Replace `CHANGE_ME` and restrict TCP 2324 to the administration network.
