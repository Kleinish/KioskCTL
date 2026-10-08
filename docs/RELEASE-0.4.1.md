# kioskctl 0.4.1

## Plugin setup form hotfix

0.4.1 fixes a Web UI regression introduced by the 0.4.0 plugin page. The normal background `/api/status` refresh re-rendered the MQTT and Home Assistant form fields from saved configuration, which could erase text while a user was typing before Save was pressed.

Plugin configuration forms are now dirty-aware:

- MQTT and Home Assistant fields stop syncing from background status as soon as the user edits them.
- Live badges, connection state, entity counts, and error text continue refreshing while a form is being edited.
- Unsaved edits remain intact until Save or a page reload.
- After a successful save, the form returns to normal server synchronization.
- Password fields remain write-only and are cleared only after a successful save or a pristine server sync.

No kiosk session, display, input, browser, MQTT transport, or Home Assistant discovery behavior changed in this hotfix.
