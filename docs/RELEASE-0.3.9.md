# kioskctl 0.3.9

This release is based on the September 17 multi-distro laptop test pass.

## Fixes

- Debian `--fresh` no longer depends on deleting/recreating the dedicated account. Fresh mode retains the stateless `kioskctl` identity while wiping its home and every kioskctl-owned application/config/browser/runtime artifact.
- Full `uninstall.sh --purge` still removes the account and now stops `user@UID.service` plus `user-runtime-dir@UID.service` before a force-delete fallback.
- Physical touchscreen coordinates follow display rotation using a managed libinput calibration rule for normal/90/180/270 transforms.
- Touch rotation changes restart the graphical kiosk session so already-open libinput devices reload calibration.
- Input inventory uses udev `ID_INPUT_*` metadata when available, improving Wacom/ELAN touchscreen classification.
- Web UI moved one-time configuration into a side menu: Overview, Browser, Display & Input, Diagnostics, System.
- MQTT command callbacks use explicit action helpers; publisher exceptions are logged.
- Configuration mutations are guarded by a lock and status reads use a snapshot.
- Update endpoint logs detailed subprocess failures server-side and returns a generic client error.

## Fresh development install

```bash
./install.sh --fresh --enable-kiosk --url "https://example.com"
```

`--fresh` intentionally retains only the dedicated service account identity. The browser profile, home contents, config, token, policy, runtime state and application files are recreated.
