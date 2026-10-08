# kioskctl 0.4.4 — touch runtime targeting + HA URL reliability

0.4.4 keeps the proven kiosk/session and MQTT/plugin architecture unchanged and fixes issues found during the Arch + Home Assistant touch-feature test.

## Fixed

- DevTools no longer blindly selects the first Chromium `page` target. Chromium 153 may expose an internal top-chrome WebUI page before the real kiosk content page; kioskctl now prefers external HTTP/HTTPS/file targets and favors the configured kiosk origin.
- Pull-to-refresh, the edge drawer and the in-page keyboard are therefore injected into the actual kiosk document. Runtime injection is verified after installation, and failures identify the selected target in the kiosk session log.
- Home Assistant `Current URL` now uses an explicit current-URL-or-configured-URL template and benefits from the corrected DevTools target selection.
- Brightness is clamped to 1–100 before the display provider is invoked.
- Volume is clamped to 0–100 before the audio provider is invoked.

## Notes

The low-level display and audio providers already clamped their values defensively in 0.4.3, so the external review correctly identified the route-ordering defect but the hardware backend was not actually receiving unbounded values. 0.4.4 fixes the API boundary as well so both layers are correct.

No graphical startup/session changes are included in this release.
