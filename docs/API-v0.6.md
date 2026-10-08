# Management API v0.6

`GET /api/health` is unauthenticated. Other `/api` routes require `X-API-Key: TOKEN` unless authentication is disabled. Requests and responses use JSON.

Stable groups are `/api/status`, `/api/diagnostics`, `/api/browser/*`, `/api/display/*`, `/api/input/*`, `/api/idle/*`, `/api/screensaver/*`, `/api/mqtt/*`, and `/api/plugins/*`. v0.6 retains v0.5.2 route names for UI compatibility.

External plugin calls use `POST /api/plugins/{id}/call` with `{"method":"status","params":{}}`. The host verifies manifest permissions against `plugins.{id}.granted_permissions`.

Errors use an appropriate status and `{"detail":"message"}`. Do not expose the API to the public Internet.
