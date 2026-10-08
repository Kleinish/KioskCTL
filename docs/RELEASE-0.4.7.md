# kioskctl 0.4.8 — touch gesture hardening + kiosk input polish

This release keeps the proven Cage/session/plugin architecture from 0.4.6 and tightens the physical browser interaction layer.

- Pull-to-refresh now tracks native touchscreen `touchstart` / `touchmove` / `touchend` with a non-passive move handler. It no longer depends on Pointer Events that Chromium may cancel when scrolling begins, and it no longer re-checks scroll position mid-gesture.
- The on-screen keyboard is hidden on every new document, does not open from page autofocus, and automatically opens only after a physical touch/stylus tap into an editable field. Remote Web UI text and key entry hides the physical keyboard before sending CDP input.
- The remote kiosk mouse cursor hides after 1.8 seconds of inactivity, reappears on mouse/trackpad activity, and stays hidden for touch interaction.
- Dark page mode now combines `prefers-color-scheme: dark` with Chromium's `Emulation.setAutoDarkModeOverride` when available, so sites that ignore the CSS preference can still be force-rendered dark. Older Chromium builds transparently fall back to media emulation.
- Dashboard health indicators now live in the sticky Dashboard header as compact status pills. Threshold configuration remains under System.

No tty/logind/Cage/OpenRC startup behavior is changed in this release.
