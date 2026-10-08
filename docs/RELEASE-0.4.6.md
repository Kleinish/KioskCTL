# kioskctl 0.4.6 — dashboard health lights + settings cleanup + kiosk page theme

This release keeps the proven Cage/Chromium/session and 0.4.5 runtime-monitor paths intact and focuses on operator UX.

## Web administration

- **Overview** is renamed **Dashboard**.
- Browser and Display & Input are grouped beneath one **Settings** navigation item with Browser and Display & Input sub-tabs.
- CPU, memory, disk, temperature, uptime and browser runtime cards move to **System**.
- Dashboard gains compact health indicator lights for CPU, memory, disk, temperature and browser state.
- CPU, memory, disk and CPU-temperature alert thresholds are configurable under System. `0` disables an individual threshold.
- The full current kiosk URL is available as hover text on the Remote screen section even when the visible line is truncated.
- Existing responsive wrapping from 0.4.5 remains in place.

## Physical kiosk controls

- The edge drawer's Close control is now pinned to the bottom and styled red so it is visually distinct from navigation/actions.
- Pull-to-refresh, the on-screen keyboard and the edge drawer continue to be maintained by the persistent runtime monitor introduced in 0.4.5.

## Remote Chromium page theme

A new Browser setting controls the kiosk page's preferred color scheme through the Chrome DevTools Emulation domain:

- Auto / system
- Light
- Dark

The runtime monitor reapplies the configured preference when Chromium replaces the active page target. This controls the content rendered by the remote Chromium kiosk rather than only the kioskctl admin UI. Home Assistant discovery also exposes a **Browser Theme** select using the generic MQTT `theme` command.

## API

- `POST /api/browser/color-scheme` — persist and immediately apply `auto`, `light`, or `dark`.
- `POST /api/monitoring/config` — update Dashboard health thresholds.
- `GET /api/status` now includes `browser_experience.color_scheme` and `monitoring.thresholds`.

## Validation

The release includes regression coverage for CDP color-scheme emulation, grouped Settings navigation, dashboard threshold lights, URL hover behavior, the red bottom drawer Close control, Home Assistant Browser Theme discovery, config validation and synchronized version metadata.
