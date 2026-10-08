# v0.6 Test-build status

This repository is a work-in-progress Rust migration, not a feature-complete
replacement for v0.5.2 yet.

## Authentication

The installer preserves `/etc/kioskctl/config.yaml`, including
`admin.auth.token`. Use the same API token that was used with v0.5.2; do not
rotate it just because a v0.6 test build is installed. A `401` response means
the browser's saved token does not match that configuration value.

Verify the token without printing it:

```sh
curl -i -H 'X-API-Key: YOUR_EXISTING_TOKEN' http://127.0.0.1:2324/api/status
```

`200 OK` confirms authentication. The web browser stores its entered token in
that browser profile's local storage, so it may need to be entered again after
a profile reset.

## WIP6 browser test

WIP6 enables the browser service during installation and adds a Chromium DevTools
Protocol (CDP) backend for screenshots, navigation, reload/back, and remote
click/text/key input. After installation, verify both services before opening
the management UI:

```sh
sudo systemctl --no-pager --full status kioskctl-agent kioskctl-browser
curl -i http://127.0.0.1:2324/api/health
```

On Alpine, use `rc-service kioskctl-agent status` and
`rc-service kioskctl-browser status` instead. If the browser service fails,
capture its complete service log; do not treat an unavailable screenshot as an
API-token failure.

WIP9 sends Enter as a Chromium `keyDown` event with carriage-return text. Test
it after clicking a harmless, focused form field; Tab and Backspace already
use their native CDP paths.

WIP10 adds provider-backed display power, brightness, and volume controls.
Brightness requires `brightnessctl`; volume prefers PipeWire (`wpctl`) and
then PulseAudio (`pactl`). Display power requires `wlr-randr` and uses the
kiosk user's live Wayland socket. An unavailable slider is expected on hosts
without that hardware or provider.

WIP12 restores the diagnostic-report response used by the Web UI, adds ALSA
(`amixer`) as the final volume-provider fallback, and makes the Reboot and
Shutdown buttons invoke the configured system power action. Test only Reboot
until the host can be recovered through SSH or a local console. When display
power or audio remains unavailable, use the Diagnostics panel: its
`wayland-output` and `audio` rows are the information needed to select the
next provider fix.

WIP15 invokes the systemd browser-session script through `/bin/sh`. This
avoids Fedora `203/EXEC` failures caused by direct execution policy or mount
labels while preserving the same session script and arguments.

## What this test build proves

- The Rust binary builds and the service starts on Fedora, Debian, and Alpine.
- Configuration migration and token-gated health/status endpoints work.
- The v0.5-derived web client can display the compatibility status document
  and identifies the running Rust agent as v0.6.0.

## Known limitations

The compatibility document is only a bridge for the existing web UI. Browser
control, screenshots, remote input, display/audio backends, MQTT, and built-in
provider behavior still require their Rust implementations. Buttons for those
unfinished capabilities must not be used as evidence of v0.5 feature parity.
