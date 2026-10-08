# kioskctl 0.3.5

Production-hardening release following external code review of 0.3.4.

## Reliability fixes

- Added a 10-second timeout to SELinux `restorecon`; a timeout now produces a clear error instead of hanging session management indefinitely.
- Corrected Alpine/seatd diagnostics so a regular file at `/run/seatd.sock` cannot be reported as a healthy socket.
- Centralized validation for browser DevTools, admin Web UI, and MQTT ports; valid range is 1–65535.
- Added explicit config-schema migration for v1/v2 -> v3 and rejection of future unsupported schema versions.
- Display startup helper now logs a warning if Chromium DevTools never becomes available for the geometry-refresh step.
- Interactive CLI commands now return concise errors instead of Python tracebacks. Set `KIOSKCTL_DEBUG=1` when a full traceback is desired.
- Documented the intentional Chromium notification enum difference between managed policy and profile Preferences.

## Architecture

The tty/logind/Cage startup path proven on Ubuntu, Debian, Arch, Fedora and Alpine is unchanged in this release.
