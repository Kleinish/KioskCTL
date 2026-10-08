# kioskctl 0.4.0

## Plugin architecture milestone

This release intentionally leaves the 0.3.10 graphical/session implementation unchanged and adds the first integration architecture above it.

### Core

- Added `EventBus` for internal capability/event notifications.
- Added `PluginManager` with built-in plugin lifecycle and status reporting.
- MQTT is now a generic transport, not a Home Assistant integration.
- MQTT logs connection, disconnect, subscription and publish failures and exposes live connection status to the API/Web UI.
- Generic MQTT commands now include browser restart, brightness, rotation and display reinitialize in addition to the existing URL/reload/screen/volume/reboot commands.

### Home Assistant plugin

- Moved HA discovery to `kioskctl/plugins/homeassistant.py`.
- Preserves legacy Status, Reboot and Reload Browser discovery topics/unique IDs.
- Adds Browser, Current URL, Screen, Brightness, Volume, Rotation, URL, Restart Browser, Reinitialize Display, CPU Usage, Memory Usage and CPU Temperature.
- Removes the old invalid `enum` device class from Status discovery.
- Subscribes to `homeassistant/status` and republishes retained discovery when HA comes online.
- Adds manual **Republish discovery** action.

### Web UI

New **Plugins** page includes:

- MQTT enable/disable, host, port, username, password and base topic.
- Password is write-only from the UI; the API reports only whether a password is stored.
- Live MQTT connected/disconnected state and last error.
- Home Assistant plugin enable/disable and discovery prefix.
- Entity count, last discovery publish, and manual republish button.

### Configuration migration

Config schema is now v4. In-place upgrades migrate the old `mqtt.home_assistant_discovery` and `mqtt.discovery_prefix` values into `plugins.homeassistant` automatically. Fresh installs start with MQTT and the Home Assistant plugin disabled and can be configured entirely from the Web UI.
