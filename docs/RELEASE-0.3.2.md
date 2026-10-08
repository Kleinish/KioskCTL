# kioskctl 0.3.2

V0.3.2 is a graphical-session hotfix from simultaneous Debian, Arch, Fedora and Alpine testing.

Fixes:
- Do not export `WAYLAND_DISPLAY` before Cage starts. Pre-setting it made wlroots choose a nested Wayland backend and fail to connect to a non-existent compositor on Arch/Fedora.
- Remove Cage `-D`; Debian 13 Cage 0.2.x does not implement that option. Debug logging remains available through wlroots environment/logging instead of a Cage CLI flag.
- Reset failed `getty@tty1.service` before restart so a prior start-limit does not block recovery.
- Clear inherited invalid D-Bus and X11 display environment in the dedicated kiosk session.
- Synchronize installer/package/API/Web UI version reporting.
- Use a hostname fallback that works even when the `hostname` command is absent.
