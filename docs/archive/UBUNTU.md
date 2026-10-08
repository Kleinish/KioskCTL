# Ubuntu notes — kioskctl 0.3

Ubuntu uses Canonical's Chromium Snap at `/snap/bin/chromium`. kioskctl treats this as a first-class provider and stores the profile at:

```text
/home/kioskctl/snap/chromium/common/kioskctl-profile
```

The dedicated `kioskctl` user owns the graphical seat0/tty1 session. Your administrator account is never modified.

```bash
sudo ./install.sh --url "https://example.com"
sudo kioskctl enable-kiosk
sudo kioskctl doctor --json
```

V0.3's prompt suppression is profile-based so it also works inside Snap confinement.
