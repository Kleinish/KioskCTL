# kioskctl 0.3.0 release notes

V0.3.0 is the first release built from a five-distribution physical test matrix.

## Fixed / targeted

- Browser-native password and notification prompts not visible in DevTools screenshots.
- Arch initial half-screen/viewport mismatch that cleared after Screen Off → Screen On.
- Remote text path that became reliable only after the same Arch output reprobe.
- Fedora and Alpine incorrect temperature selection.
- Alpine missing volume control when PipeWire was unavailable as a user-session provider.
- Cross-platform troubleshooting requiring different ad-hoc shell commands.

## New

- Browser prompt profile management.
- Display settle/apply stage before Chromium launch.
- Display output/mode/rotation/scale configuration.
- Display reinitialize command/API/UI.
- Focus + viewport diagnostics for remote input.
- Ranked hwmon/thermal sensor inventory.
- PipeWire/PulseAudio/ALSA audio fallback.
- Diagnostics Web UI + API.
- `sudo kioskctl doctor --json`.
- OpenRC/seatd Alpine graphical session on VT7.
- V0.2 configuration migration/preservation.
