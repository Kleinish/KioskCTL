# API reference — kioskctl 0.5.1

All protected endpoints require:

```text
X-API-Key: <token>
```

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Agent health, no auth |
| GET | `/api/status` | System/browser/display/provider status |
| GET | `/api/diagnostics` | Cross-distro diagnostic report |
| GET | `/api/temperature/sensors` | Enumerated/ranked thermal sensors |
| GET | `/api/screenshot` | PNG screenshot of current Chromium page |
| GET | `/api/input/focus` | Focused DOM element metadata |
| GET | `/api/input/devices` | Linux input-device inventory/classification |
| POST | `/api/input/click` | Normalized remote click; `{ "x": 0..1, "y": 0..1 }` |
| POST | `/api/input/text` | Insert text into focused page control |
| POST | `/api/input/key` | Send common key such as Enter/Tab/Escape/Backspace |
| POST | `/api/input/config` | Configure physical touch rotation and touchscreen compatibility-pointer suppression |
| POST | `/api/browser/url` | Navigate and persist Home URL |
| POST | `/api/browser/navigate` | Navigate to a configured page name or explicit URL |
| POST | `/api/browser/experience` | Configure named pages, zoom, pull-to-refresh, edge drawer, on-screen keyboard and kiosk page color scheme |
| POST | `/api/browser/color-scheme` | Persist/apply kiosk page theme: `auto`, `light`, or `dark` |
| POST | `/api/browser/reload` | Reload page, restart session if CDP unavailable |
| POST | `/api/browser/back` | Browser history back |
| POST | `/api/browser/restart` | Restart kiosk session |
| POST | `/api/browser/prompts` | Configure password/notification/autofill/translate prompts |
| POST | `/api/kiosk/enable` | Enable graphical kiosk |
| POST | `/api/kiosk/disable` | Disable graphical kiosk |
| POST | `/api/display/on` | Enable Wayland output(s) and reapply geometry |
| POST | `/api/display/off` | Disable Wayland output(s) |
| POST | `/api/display/reinitialize` | Power-cycle/reprobe output and reapply geometry |
| POST | `/api/display/config` | Persist/apply output/mode/refresh/scale/transform plus touch rotation/pointer-suppression settings |
| POST | `/api/display/brightness` | `{ "percent": 1..100 }` |
| GET | `/api/idle/status` | Idle/dim/off/wake state and monitored local input devices |
| POST | `/api/idle/config` | Configure idle dim/off timers, dim brightness and wake-on-input |
| POST | `/api/audio/volume` | `{ "percent": 0..100 }` using PipeWire/Pulse/ALSA provider |
| POST | `/api/monitoring/config` | Configure Dashboard CPU/memory/disk/temperature alert thresholds |
| POST | `/api/system/reboot` | Reboot host |
| POST | `/api/system/shutdown` | Power off host |
| POST | `/api/system/update` | Run configured update command |

Interactive OpenAPI documentation is served at `/api/docs`.


## MQTT / plugins (0.5.0)

- `GET /api/mqtt/status` — sanitized MQTT transport status (never returns the stored password).
- `POST /api/mqtt/config` — configure/reconnect generic MQTT transport. Blank password preserves the stored secret.
- `GET /api/plugins` — plugin status map including manifest metadata.
- `GET /api/plugins/manifests` — plugin manifest/capability/permission/config-schema metadata.
- `POST /api/plugins/homeassistant/config` — enable/disable Home Assistant and set discovery prefix.
- `POST /api/plugins/homeassistant/republish` — republish retained Home Assistant discovery.
- `GET /api/plugins/catalog` — bundled plugin catalog including manifest, install and enable state.
- `POST /api/plugins/{plugin_id}/install` — install an optional bundled catalog plugin (`digital_signage` or `immich`).
- `DELETE /api/plugins/{plugin_id}` — remove/disable an optional bundled plugin while retaining its saved settings/assets for reinstall.
- `GET /api/plugins/digital_signage/assets` — Digital Signage asset inventory.
- `POST /api/plugins/digital_signage/config` — configure signage timing, image fit and schedule.
- `POST /api/plugins/digital_signage/assets` / `DELETE /api/plugins/digital_signage/assets/{name}` — manage signage images.
- `POST /api/plugins/digital_signage/preview` — preview the Digital Signage provider.
- `POST /api/plugins/immich/config` — configure Immich server/API key/album/timing. A blank API key preserves the stored secret.
- `POST /api/plugins/immich/test` — test Immich connectivity and fetch an image pool.
- `POST /api/plugins/immich/preview` — preview the Immich provider.

## Simple screensaver (core)

Authenticated management endpoints:

- `GET /api/screensaver/images`
- `POST /api/screensaver/images` — JSON body `{name, data_base64}`; PNG/JPEG/WebP/GIF up to 15 MiB
- `DELETE /api/screensaver/images/{name}`
- `POST /api/screensaver/config`
- `POST /api/screensaver/preview`
- `POST /api/screensaver/stop`

The physical browser uses loopback-only `/screensaver` and `/screensaver/image/{name}` routes; remote clients are denied access to those playback routes.


### Screensaver / idle coordination (0.4.10)

`POST /api/screensaver/config` accepts `keep_display_on` (boolean). It defaults to `true`; while a local slideshow is active, kioskctl keeps the output powered and restores pre-idle brightness instead of allowing the idle dim/off policy to hide the signage.


## Touch pointer suppression (0.4.10)

`input.ignore_touch_mouse_emulation` defaults to `true`. kioskctl detects mouse event nodes whose Linux `Phys=` identifier is shared with a touchscreen and marks only those nodes `LIBINPUT_IGNORE_DEVICE=1`. This avoids a compositor cursor being kept alive by touchscreen compatibility mouse events while preserving independent touchpads and USB mice. The managed udev rule is `/etc/udev/rules.d/99-kioskctl-touch-pointer.rules`.

The setting is accepted by both `POST /api/input/config` and `POST /api/display/config`. Changing it while the kiosk is enabled restarts the graphical kiosk session so Cage/libinput reopens the affected event nodes.

## Screensaver history behavior (0.4.10)

The local slideshow uses `location.replace()` to enter and leave `/screensaver`. The temporary slideshow therefore does not become a browser-history entry, so a later Back gesture returns to the user's previous web page rather than unexpectedly reopening the screensaver.


## Plugin idle-content playback (0.5.0)

The physical kiosk uses loopback-only plugin surfaces `/plugin/digital-signage/screen` and `/plugin/immich/screen`. Their corresponding asset/image routes are also loopback-only. The runtime monitor treats these surfaces like the core `/screensaver` page and does not inject the normal pull-refresh/drawer/keyboard overlay while idle content is active.

Only one idle screensaver provider is intended to be enabled at a time. The authenticated configuration APIs disable competing providers when enabling Simple screensaver, Digital Signage or Immich.

## Immich full-size image source (0.5.1)

The Immich slideshow proxy uses `/api/assets/{id}/thumbnail?size=fullsize` rather than the `preview` derivative so **Contain** can preserve the source aspect ratio. `POST /api/plugins/immich/test` now validates one real full-size image request in addition to server metadata and asset discovery. Restricted Immich API keys may therefore require both asset-view and asset-download permission when Immich redirects a browser-compatible full-size request to the original asset.
