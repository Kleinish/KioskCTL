# kioskctl 0.4.3 — Touch appliance experience

0.4.3 extends the proven 0.4.2 MQTT/Home Assistant integration with the first touch-first appliance features. The graphical startup/session architecture is unchanged.

## Added

- Pull-down-to-refresh on the physical kiosk, enabled by default. The configurable gesture threshold defaults to 110 px and respects nested scroll containers.
- Named browser pages with Home/previous/next navigation from the Web UI, MQTT and Home Assistant.
- Persistent browser zoom (50–200%).
- Optional right-edge physical-kiosk control drawer.
- Optional in-page touch keyboard.
- Idle manager with dim, display-off and wake-on-local-input policy. Idle behavior is disabled by default.
- `install.sh --fresh --preserve-integrations`, preserving only MQTT credentials and plugin configuration while the rest of kioskctl is reset.
- Plugin manifest metadata: version, capabilities, permissions and configuration schema.
- Home Assistant entities for Browser Zoom, Page, Previous Page, Next Page and Idle Display Policy.
- `/api/plugins/manifests`, `/api/browser/navigate`, `/api/browser/experience`, `/api/idle/status` and `/api/idle/config`.

## Fixed / polished

- Home Assistant Current URL discovery falls back to the configured Home URL when a live page URL is temporarily unavailable.
- Home Assistant publishes a fresh retained state immediately after discovery, avoiding an initial `Unknown` wait until the normal state heartbeat.
- MQTT/plugin settings no longer need to be re-entered on every fresh development install when `--preserve-integrations` is used.

## Notes

The on-screen keyboard is a distro-neutral in-page implementation for this first release. A native keyboard provider (for example a Wayland keyboard such as Squeekboard where available) can be added later behind the same kioskctl control surface.

The idle manager watches `/dev/input/event*` non-exclusively. Hardware where the management agent cannot open input devices will still run kioskctl normally, but wake-on-input is best-effort; the Web UI exposes the monitored-device count and last error.

Pull-down-to-refresh is injected by Chromium DevTools and therefore refreshes the physical kiosk page without depending on the hosted application's own refresh implementation.
