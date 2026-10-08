# Debian notes — kioskctl 0.3

Debian is a supported V0.3 target using native Chromium and a real systemd/logind seat0 session on tty1.

```bash
./install.sh --dry-run
sudo ./install.sh --url "https://example.com"
sudo kioskctl enable-kiosk
sudo kioskctl doctor --json
```

Recovery:

```bash
sudo kioskctl disable-kiosk
```
