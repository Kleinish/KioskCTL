# kioskctl 0.4.11

## Touchpad suppression for touch-first kiosks

0.4.11 adds a reversible **Disable touchpad while kiosk mode is active** setting under **Settings → Display & Input**.

Some touchscreen laptops expose both a working touchscreen and a built-in touchpad. Cage/wlroots sees the touchpad as a fine pointer source, so the compositor cursor can remain visible even when the kiosk is being operated entirely by touch. kioskctl can now temporarily remove touchpad event nodes from libinput while graphical kiosk mode is active.

Implementation details:

- detects Linux input nodes classified with `ID_INPUT_TOUCHPAD=1`;
- writes `/etc/udev/rules.d/99-kioskctl-touchpad.rules` only when the option is enabled;
- applies `LIBINPUT_IGNORE_DEVICE=1` to touchpad event nodes;
- reloads/retriggers udev and restarts the kiosk session so Cage/libinput reopen devices;
- leaves touchscreens, tablets/styluses, keyboards and external mice untouched;
- removes the rule automatically when `kioskctl disable-kiosk` restores the normal console;
- reapplies the saved preference when kiosk mode is enabled again;
- reports touchpad candidate count and active suppression count in status, diagnostics and the Web UI.

The option defaults to **off** so existing installs retain their trackpad until an operator explicitly enables touch-only behavior.

## Upgrade

Use an in-place upgrade to retain MQTT, Home Assistant, Chromium profile, slideshow images and kiosk settings:

```bash
unzip -o kioskctl-v0.4.11.zip
cd kioskctl-v0.4.11
sudo ./install.sh
```

Then enable **Settings → Display & Input → Disable touchpad while kiosk mode is active** and click **Apply display & input configuration**. kioskctl restarts the graphical session automatically when the setting changes.

To restore the trackpad from the command line at any time:

```bash
sudo kioskctl disable-kiosk
```

Re-enabling kiosk mode reapplies the saved touchpad preference.
