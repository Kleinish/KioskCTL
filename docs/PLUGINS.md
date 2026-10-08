# Building custom plugins

This guide describes the external-plugin interface implemented by kioskctl
v0.6 WIP12. It is language-neutral: a plugin can be written in Rust, Python,
Go, Bash, or any language that can read one JSON line from standard input and
write one JSON line to standard output.

## Important security boundary

External plugins are **trusted local programs**. kioskctl checks requested
permissions against the configuration before starting a plugin, but WIP12 does
not provide an operating-system sandbox. The plugin inherits the agent's
privileges (normally root). Only install code you have reviewed and trust.

The plugin process receives a minimal environment: `PATH=/usr/bin:/bin` and
`KIOSKCTL_PLUGIN_ID`. It does not receive API tokens or configuration secrets
through environment variables. Never put secrets in a manifest, source tree,
response JSON, or diagnostic output.

## What a plugin can do today

The host discovers manifests at startup and exposes an authenticated,
on-demand call endpoint. A plugin starts for one request, returns one response,
and exits. This suits status collectors, small integrations, and command
adapters.

It is **not yet** a persistent background-service, UI-widget, MQTT-discovery,
or automatic screensaver-provider API. Names under `capabilities` are
descriptive metadata in WIP12; they do not make the Web UI call a plugin
automatically.

## Directory layout

Install one directory per plugin below `/etc/kioskctl/plugins.d`:

```text
/etc/kioskctl/plugins.d/
└── hello/
    ├── plugin.yaml
    └── hello-plugin
```

`plugin.yaml` and its executable must both exist when `kioskctl-agent` starts.

## Manifest

```yaml
id: hello
name: Hello plugin
version: 1.0.0
description: Returns a small health document
executable: hello-plugin
capabilities: [status.provider]
permissions: [status.read]
config_schema: []
```

- `id` must match `[a-z0-9_-]+`.
- `executable` is a filename relative to the plugin directory; do not use an
  absolute path or `../` path.
- Every manifest permission must be granted in `/etc/kioskctl/config.yaml`.
- `capabilities` and `config_schema` are metadata in WIP12.
- Use a real semantic version in `version`.

Common permission names are `status.read`, `browser.navigate`, `network.http`,
`filesystem.plugin-data`, `mqtt.publish`, `mqtt.subscribe`, and `secret.store`.
Request only what the plugin needs.

```yaml
plugins:
  hello:
    granted_permissions: [status.read]
```

## Protocol

kioskctl writes one newline-delimited JSON-RPC request to standard input and
closes stdin. The plugin writes one JSON response line to standard output and
exits with status zero.

Request:

```json
{"jsonrpc":"2.0","id":1,"protocol":1,"method":"status","params":{}}
```

Success:

```json
{"jsonrpc":"2.0","id":1,"result":{"healthy":true,"message":"hello"}}
```

Error:

```json
{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"method not found"}}
```

- Protocol version is `1`.
- Preserve the request `id`.
- Write protocol output only to stdout; log to stderr.
- Finish within 10 seconds; stdout is limited to 1 MiB.
- Exit zero after a valid response.

The host passes the `result` JSON directly to the caller. Document a stable
object shape for every method.

## Minimal Python plugin

Save this as `hello-plugin`, then run `chmod +x hello-plugin`:

```python
#!/usr/bin/env python3
import json
import sys

def reply(request_id, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": request_id}
    message["result" if error is None else "error"] = result if error is None else error
    print(json.dumps(message), flush=True)

try:
    request = json.loads(sys.stdin.readline())
except json.JSONDecodeError as exc:
    reply(None, error={"code": -32700, "message": str(exc)})
    raise SystemExit(0)

request_id = request.get("id")
if request.get("protocol") != 1:
    reply(request_id, error={"code": -32600, "message": "unsupported protocol"})
elif request.get("method") == "status":
    reply(request_id, result={"healthy": True, "message": "hello from Python"})
else:
    reply(request_id, error={"code": -32601, "message": "method not found"})
```

A matching Rust example is in `examples/plugins/hello-rust`; a complete Python
example is in `examples/plugins/hello-python`.

## Test locally

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"protocol":1,"method":"status","params":{}}' \
  | ./hello-plugin
```

Expected response:

```json
{"jsonrpc":"2.0","id":1,"result":{"healthy":true,"message":"hello from Python"}}
```

## Install and invoke

```bash
sudo install -d -m 0755 /etc/kioskctl/plugins.d/hello
sudo install -m 0644 plugin.yaml /etc/kioskctl/plugins.d/hello/plugin.yaml
sudo install -m 0755 hello-plugin /etc/kioskctl/plugins.d/hello/hello-plugin
sudo chown -R root:root /etc/kioskctl/plugins.d/hello

sudoedit /etc/kioskctl/config.yaml
sudo systemctl restart kioskctl-agent
```

On Alpine, use `sudo rc-service kioskctl-agent restart`.

```bash
curl -H 'X-API-Key: YOUR_TOKEN' http://127.0.0.1:2324/api/plugins

curl -sS \
  -H 'X-API-Key: YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  --data '{"method":"status","params":{}}' \
  http://127.0.0.1:2324/api/plugins/hello/call
```

## Contributor checklist

1. Keep calls short and deterministic; do not daemonize.
2. Validate all `params` before using them in a command or URL.
3. Never assemble shell commands from untrusted parameters.
4. Send diagnostics to stderr and redact secrets.
5. Test malformed JSON, unsupported protocol, and unknown methods.
6. Document every method, parameter, and result shape in the plugin README.
7. Pin dependencies or ship a self-contained binary/script with installation
   prerequisites.

## Future compatibility

The protocol version is intentionally included in every request. Reject
unknown versions cleanly and avoid assuming that unlisted environment
variables, persistent state, or network access will remain available later.
