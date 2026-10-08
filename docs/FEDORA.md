# Fedora notes — kioskctl 0.3

Fedora is a supported V0.3 hardware-test target using native Chromium and systemd/logind.

V0.3 replaces the V0.2 "first thermal zone" behavior with ranked hwmon/thermal sensor discovery because Fedora test hardware reported the wrong temperature source.

```bash
./install.sh --dry-run
sudo ./install.sh --url "https://example.com"
sudo kioskctl enable-kiosk
sudo kioskctl doctor --json
```
