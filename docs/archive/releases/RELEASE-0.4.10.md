# kioskctl 0.4.10

0.4.10 focuses on three hardware/runtime issues exposed by the first long-running touchscreen tests.

## Touch drawer behavior

The physical kiosk edge drawer now closes when the user touches or clicks anywhere outside the drawer. The outside interaction is not consumed, so the underlying page still receives the touch/click.

## Cursor: suppress touchscreen compatibility mouse nodes

Chromium/CSS cursor hiding is not sufficient on every Wayland/Cage touchscreen. Some integrated digitizers expose both touchscreen event nodes and a compatibility `ID_INPUT_MOUSE` node. wlroots then sees a real pointer device and can leave a compositor cursor parked onscreen even when the browser has `cursor:none` active.

kioskctl now detects mouse nodes whose Linux `Phys=` identifier is shared with a detected touchscreen and can mark only those compatibility nodes with `LIBINPUT_IGNORE_DEVICE=1`. Real USB mice and independent touchpads are not matched. The option is enabled by default and is visible under **Settings → Display & Input** as **Ignore touchscreen-emulated mouse pointer**. Applying the setting restarts the graphical kiosk session so Cage/libinput reopens input devices with the new rule.

The managed rule is `/etc/udev/rules.d/99-kioskctl-touch-pointer.rules` and is removed by a kioskctl purge.

## Screensaver no longer pollutes browser history

The local slideshow previously entered and exited with ordinary `Page.navigate` calls. That left `/screensaver` in Chromium history, so a later browser-back gesture could unexpectedly return to the slideshow. Screensaver entry/exit now uses `location.replace()`, preserving the user's normal page history.

## Slideshow asset inventory

The screensaver settings UI now refreshes its image inventory from the dedicated `/api/screensaver/images` endpoint when the Display & Input settings pane is opened and after upload/delete operations. This prevents transient status/UI state from showing an empty list while preserved image files are still present on disk.

## Configuration schema

Schema v8 adds `input.ignore_touch_mouse_emulation` (default `true`). Existing v7 configurations migrate automatically.
