# kioskctl 0.4.2

0.4.2 fixes the Plugins-page save regression found while configuring the first Home Assistant test device.

## Fixed

- **MQTT and Home Assistant Save buttons now submit JSON correctly.** In 0.4.0/0.4.1 the two FastAPI routes were registered before their Pydantic request-body classes were defined. Because `from __future__ import annotations` postponed the annotations, FastAPI registered `body` as a query parameter instead of a JSON body. The browser therefore received HTTP 422 when Save was clicked.
- Moves `MQTTConfigBody` and `HomeAssistantConfigBody` above route registration so FastAPI builds the correct request-body schema.
- Adds a regression test that inspects FastAPI's route dependency model and verifies both endpoints expose `body` as a body parameter, not a query parameter.
- Adds visible inline save progress/success/failure messages on the Plugins page. Errors are no longer visible only in the System activity log.
- Keeps the 0.4.1 dirty-form protection so background status refreshes cannot erase unsaved edits.

## Upgrade

This is an in-place Web/API hotfix. Do **not** use `--fresh` when upgrading from 0.4.0/0.4.1 if you want to keep the current kiosk configuration.

```bash
unzip -o kioskctl-v0.4.2.zip
cd kioskctl-v0.4.2
sudo ./install.sh
```
