# Configuration reference

The default is `/etc/kioskctl/config.yaml`; override it with `--config` or `KIOSKCTL_CONFIG`.

| Section | Purpose |
|---|---|
| `device` | Friendly kiosk name |
| `browser` | URL, executable/profile, tabs, zoom, touch UI, prompts |
| `launcher` | Optional native/local application launched instead of Chromium |
| `admin` | Bind address, port, API-token authentication |
| `system` | User, TTY/session service, power-action policy |
| `display` | Output, mode, refresh, scale, transform, brightness |
| `input` | Touch rotation and pointer/touchpad suppression |
| `monitoring` | CPU, memory, disk, temperature thresholds |
| `idle` | Dimming, panel-off, wake policy |
| `screensaver` | Local image slideshow |
| `mqtt` | Broker credentials and base topic |
| `plugins` | Built-ins, external directory, permission grants |

Secrets remain in the root-owned config. API responses reveal only whether a secret is set. Empty password/API-key updates preserve the stored value.

Use `kioskctl --config ./config.yaml check-config` to validate, or `print-config` for a redacted merged view.

## Native application launcher

By default, kioskctl starts Chromium and exposes the screenshot, remote input, page, and CDP controls in the dashboard. To run a local graphical application instead, set an absolute executable path in `launcher.command`:

```yaml
launcher:
  command: /opt/my-kiosk-app/my-kiosk-app
  args: ["--fullscreen"]
  working_directory: /opt/my-kiosk-app
  environment:
    APP_THEME: dark
```

The command runs inside the same Cage/Wayland session as Chromium would. An empty `launcher.command` restores the Chromium kiosk. Native applications do not provide Chromium DevTools, so the dashboard's screenshot, remote browser input, navigation, and configured-page controls are unavailable; hardware controls, diagnostics, plugins, and the management API remain available.
