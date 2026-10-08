# kioskctl 0.3.6

Web UI and graphical-session state synchronization release.

## Fixes

- Leaves the proven tty/logind/Cage/OpenRC startup path unchanged.
- Probes all safe runtime directories instead of trusting a preserved legacy runtime path.
- Fixes Alpine upgrades where config referenced `/run/kioskctl` but Cage runs under `/run/kioskctl-user`.
- The graphical display helper publishes `kioskctl-display.json` inside the live user runtime directory.
- The management agent uses that snapshot as a read-only fallback when direct `wlr-randr` probing is unavailable.
- Avoids duplicate display probes while computing browser/display geometry.
- Adds a `display_source` field (`live`, `session-snapshot`, or `none`) for troubleshooting.
- Version-busts Web UI CSS/JavaScript and serves admin assets with no-cache headers.
- Web UI Hardware and Display sections render independently, so one bad field cannot leave the rest of the dashboard stale.
- Diagnostics refresh automatically every 30 seconds and reports the display-data source.
- Multi-exec health check now falls back to `wget` when `curl` is not installed and reports all known runtime directories.
