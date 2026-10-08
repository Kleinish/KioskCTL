# kioskctl 0.3.4

Hardware-control stabilization release following successful graphical-session bring-up on Ubuntu, Debian, Arch, Fedora and Alpine.

## Fixes

- Dynamic Wayland socket discovery for agent-side `wlr-randr` control.
- Root-to-kiosk command execution regression caused by a missing `os` import.
- PipeWire/Pulse/ALSA provider probing from the correct kiosk-user runtime.
- Display geometry diagnostics and Wayland socket reporting.
- Remote text fallback for iframe/app focus using CDP `Input.dispatchKeyEvent` char events.
- Native Chromium managed policy for password, notification, autofill and translation prompt suppression.
- Multi-exec hostname/Wayland-socket diagnostics.

## UI/API additions

- Refresh-rate control.
- Geometry match/mismatch status.
- Input-device inventory.
- `GET /api/input/devices`.
- `status.input_devices`, `status.geometry`, and `status.wayland_display`.

## Deliberately unchanged

The graphical startup/session architecture from 0.3.2/0.3.3 is frozen for this release. No tty/getty/Cage/OpenRC session changes were made.
