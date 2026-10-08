# Roadmap

## 0.5.x — plugin catalog / idle-content providers

- Bundled optional Digital Signage and Immich Screensaver plugins: **0.5.0**.
- Core Simple screensaver remains available without plugins.
- Next: isolated/signed external plugin packages behind the same catalog UI, followed by additional camera/presence/media integrations.


## V0.3 — multi-distro daily-driver foundation

- [x] Ubuntu/Debian/Arch/Fedora/Alpine package detection
- [x] Chromium native + Ubuntu Snap providers
- [x] Dedicated graphical account and recovery-safe session architecture
- [x] OpenRC + seatd Alpine session path
- [x] Authenticated Web UI + REST API
- [x] Screenshot/click/text/key remote control
- [x] Browser prompt suppression
- [x] Display output/mode/rotation/scale configuration
- [x] Startup display stabilization before Chromium launch
- [x] Display reinitialization/reprobe action
- [x] CPU-oriented hwmon/thermal sensor selection
- [x] PipeWire/PulseAudio/ALSA audio fallback
- [x] Cross-distro diagnostics and `kioskctl doctor --json`
- [x] Upgrade-safe config preservation
- [ ] Complete hardware validation matrix
- [ ] Touchscreen rotation/mapping validation
- [ ] Multi-monitor layout controls
- [ ] DDC/CI external-monitor brightness

## V0.4 — appliance experience

- [x] Core event bus + built-in plugin manager
- [x] Home Assistant reference plugin + generic MQTT transport
- [x] Plugin manifest/capability/permission/config-schema metadata
- [x] Multi-page navigation and browser zoom
- [x] Pull-down-to-refresh
- [x] Optional physical-kiosk edge controls
- [x] Optional in-page on-screen keyboard
- [x] Idle dim/display-off + wake-on-local-input foundation
- [x] Preserve MQTT/plugin settings across development `--fresh` installs
- [ ] Screensaver plugin: clock/local photos/Immich
- [ ] Cursor auto-hide policy
- [ ] External plugin discovery/loading and plugin-provided UI panels
- [ ] Wi-Fi provisioning/recovery overlay
- [ ] Config export/import
- [ ] Signed update metadata + rollback hooks

## V0.5 — fleet

- Central fleet controller
- Device enrollment
- Device groups and profiles
- Bulk URL/config/display actions
- Staged updates and rollback
- Fleet screenshots/health
- Role-based access control

## Later plugin ideas

- Home Assistant discovery/control
- Digital signage scheduler/playlists
- Presence/motion
- Photo frame/screensavers
- Camera/intercom
- Media player
- GPIO/serial hardware
- NFC/RFID/barcode
- Notifications/overlays


## V0.3.4 — hardware-control stabilization

- Dynamic Wayland socket discovery
- Cross-distro display/audio provider context fixes
- Refresh rate and geometry validation
- Stronger prompt suppression
- Input device inventory
- Remote text iframe fallback

## V0.3.8 / V0.4 candidates

- Per-touchscreen output mapping/calibration
- Cursor auto-hide modes
- Idle/screensaver behavior
- Plugin/event bus foundation
- Home Assistant as the first reference plugin

## 0.4.0 plugin foundation (implemented)

- Core in-process event bus.
- Built-in plugin manager/lifecycle/status API.
- Generic MQTT transport separated from Home Assistant behavior.
- Home Assistant is the first built-in plugin and owns MQTT discovery/birth handling.
- Web UI Plugins page for MQTT transport and Home Assistant configuration.

0.4.3 adds manifest/capability/permission/config-schema metadata to the built-in plugin contract. Next plugin work is external plugin discovery/loading plus plugin-provided UI panels. The manager intentionally keeps plugins built-in until that loader is proven without destabilizing the working kiosk/session layer.
