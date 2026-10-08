# kioskctl 0.6.0

`kioskctl` turns a Linux machine into a remotely managed kiosk. It launches Chromium by default and can instead launch a configured local graphical application. Version 0.6 replaces the Python agent with one Rust binary while retaining the v0.5 configuration and management UI.

## Features

- Chromium/Chrome kiosk launch and remote navigation
- Optional local/native application launcher in the same Wayland kiosk session
- Wayland display, brightness, input, touch, and audio controls
- Idle dim/off behavior and local slideshow
- MQTT and Home Assistant discovery
- Digital Signage and Immich screensavers
- Third-party plugins through a language-neutral JSON protocol
- systemd and OpenRC packaging, diagnostics, and upgrade rollback

## Install or upgrade

Install Rust 1.88+ and the platform packages listed in [Installation](docs/INSTALLATION.md), then:

```bash
tar -xf kioskctl-v0.6.0.tar.gz
cd kioskctl-v0.6.0
sudo ./install.sh
```

The installer preserves `/etc/kioskctl/config.yaml`, creates timestamped backups, validates the migrated config, and restarts only the management agent. Open `http://KIOSK-IP:2324` and enter the token from `admin.auth.token`.

## Developer quick start

```bash
cargo test
cargo run -- --config examples/config.yaml check-config
cargo run -- --config examples/config.yaml serve
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Installation](docs/INSTALLATION.md)
- [Configuration](docs/CONFIGURATION.md)
- [Build on WSL](docs/BUILDING.md)
- [Management API](docs/API-v0.6.md)
- [Custom plugin guide](docs/PLUGINS.md)
- [Migration and rollback](docs/MIGRATION-0.5-to-0.6.md)
- [Release notes](docs/RELEASE-0.6.0.md)
- [Development checkpoints](CHECKPOINTS.md)

## License

MIT. See [LICENSE](LICENSE).
