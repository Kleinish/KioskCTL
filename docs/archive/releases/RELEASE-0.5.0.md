# kioskctl 0.5.0

## Plugin catalog + signage providers

0.5.0 is the first release where advanced idle content is separated from the kiosk core. The existing local slideshow remains as **Simple screensaver** for normal kiosk deployments. Digital Signage and Immich are optional bundled plugins installed and configured from **Settings → Plugins**.

### Simple screensaver stays in core

The core screensaver still supports local PNG/JPEG/WebP/GIF uploads, start delay, interval, contain/cover fit, background, shuffle, preview, wake/restore behavior and keep-display-awake policy. It requires no plugin installation or external service.

### Digital Signage plugin

- bundled but not installed/enabled by default;
- local signage assets stored under `/var/lib/kioskctl/plugins/digital-signage/assets`;
- start delay and slide interval;
- contain/cover, background and shuffle;
- optional weekday/time schedule, including overnight windows;
- preview/return controls;
- keeps the display awake by default while signage is active.

### Immich Screensaver plugin

- bundled but not installed/enabled by default;
- write-only API key in the Web UI;
- optional album ID or randomized image pool;
- connection test before activation;
- previews are proxied through the loopback-only kioskctl service so the browser page is never given the Immich API key;
- configurable delay, interval, fit, background and display-awake behavior.

The plugin uses current Immich API patterns: API-key authentication via `x-api-key`, random image search via `/api/search/random`, and asset preview thumbnails via `/api/assets/{id}/thumbnail`.

### Plugin catalog

The Web UI catalog can install/remove the two optional bundled plugins and displays each manifest's capabilities and permissions. This release intentionally does **not** load arbitrary third-party ZIP/URL code into the privileged kioskctl agent. The catalog API is structured so a future isolated/signed external plugin host can back the same UI without changing the operator workflow.

### Provider arbitration

Exactly one idle screensaver provider is expected to be enabled. Enabling Simple screensaver, Digital Signage or Immich disables the other providers. If a scheduled signage plugin is enabled but currently outside its schedule, kioskctl leaves the normal kiosk visible instead of falling back to unrelated simple-screensaver content.

### Upgrade

Recommended from 0.4.11:

```bash
unzip -o kioskctl-v0.5.0.zip
cd kioskctl-v0.5.0
sudo ./install.sh
sudo kioskctl restart-kiosk
```

This preserves the existing kiosk configuration, Home Assistant/MQTT settings, browser profile and core screensaver assets.

For a development reset while preserving integration/plugin configuration:

```bash
sudo ./install.sh --fresh --preserve-integrations --enable-kiosk --url "https://example.com"
```

A full fresh reset still removes local plugin assets under `/var/lib/kioskctl`; use an in-place upgrade when signage assets must be retained.
