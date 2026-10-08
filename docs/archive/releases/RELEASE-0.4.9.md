# kioskctl 0.4.10

0.4.10 is a focused kiosk-runtime and Web UI reliability release.

## Fixed

- The local slideshow now takes precedence over idle dim/screen-off by default. This fixes the case where both timers reach their threshold together and the slideshow appears only briefly during wake because the display had been powered off immediately after navigation.
- Added `screensaver.keep_display_on` (default `true`) plus a Web UI checkbox: **Keep display awake while slideshow is active**.
- When signage starts after the panel has already dimmed or powered off, kioskctl restores display power and the saved brightness before showing the slideshow.
- Cursor auto-hide now uses a 250 ms watchdog and the timestamp of the last real physical mouse movement. Touch activity, pull-to-refresh, and edge-drawer navigation explicitly hide the cursor so layout/navigation-generated pointer events cannot leave it permanently visible.
- The runtime monitor recognizes `http://127.0.0.1:<port>/screensaver` as an intentional full-screen target and stops logging missing pull/edge/keyboard injection warnings while the slideshow is active.

## Web UI

- Dashboard header gets a compact **MODE** light: `ACTIVE`, `DIM`, `SLEEP`, or `SAVER`.
- Activity moves to the top of the System page.
- Screensaver settings expose whether signage should keep the panel awake.

## Configuration schema

Schema version is now **7**. v6 configurations migrate automatically and receive `screensaver.keep_display_on: true`.
