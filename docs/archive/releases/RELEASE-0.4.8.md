# kioskctl 0.4.8 — slideshow screensaver + Web UI consolidation

## What changed

- **Local slideshow screensaver** independent of Immich. Upload PNG/JPEG/WebP/GIF assets from the Web UI; configure idle delay, slide interval, contain/cover fit, background color and shuffle. Assets are stored in `/var/lib/kioskctl/screensaver` and served only to the local kiosk browser for playback.
- **Screensaver preview/return** controls in Settings → Display & Input. Normal local keyboard/mouse/touch activity dismisses the slideshow and restores the page that was open before the screensaver started.
- **Persistent Chromium dark mode.** Selecting Dark now restarts Chromium with `--force-dark-mode` and `WebContentsForceDark` in addition to the existing DevTools media preference. Light/Auto likewise restart so old launch flags cannot remain in effect.
- **Cursor hardening.** The kiosk cursor starts hidden, touch activity keeps it hidden, and touch-generated/synthetic mouse events no longer leave a pointer parked after pull-refresh or drawer navigation. Real mouse/trackpad movement still reveals the cursor temporarily.
- **Dashboard power actions.** Reboot and Shutdown are available in the Dashboard header beside health indicators.
- **Plugins moved into Settings.** Browser, Display & Input, and Plugins now share the Settings workspace; the Plugins sidebar entry is removed.
- **Diagnostics moved into System.** The standalone Diagnostics sidebar page is removed; the same diagnostics panel and refresh action now live on the System page.
- Config schema advances to **v6** for the built-in screensaver settings; v5 configs migrate automatically.

## Upgrade

Use an in-place upgrade to retain browser state, MQTT/Home Assistant settings and uploaded slideshow assets:

```bash
unzip -o kioskctl-v0.4.8.zip
cd kioskctl-v0.4.8
sudo ./install.sh
sudo kioskctl restart-kiosk
```

A `--fresh` purge intentionally deletes `/var/lib/kioskctl`, including uploaded slideshow assets.

## Validation

The packaged tree passes Python compilation, shell/JavaScript syntax checks, installer dry-run, and the full regression suite.
