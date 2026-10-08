# kioskctl 0.4.5 — persistent touch runtime + responsive admin themes

This release fixes the lifecycle problem exposed by Home Assistant OAuth navigation and polishes the management UI without changing the proven Cage/logind startup architecture.

## Browser runtime lifecycle

- Adds a long-lived `kioskctl.runtime_monitor` beside Cage.
- Retries touch/runtime injection when a DevTools target navigates, closes, or is replaced.
- Reinstalls runtime helpers when the selected external page target changes.
- Uses `Page.addScriptToEvaluateOnNewDocument` with `runImmediately` when supported, with a compatibility fallback.
- Separates display fixup from browser-runtime installation so a transient OAuth redirect cannot permanently disable pull-to-refresh, the edge drawer, or the on-screen keyboard.

## Admin UI

- Adds a persistent light/dark mode toggle in the sidebar.
- Honors the operating-system color preference on first use.
- Prevents horizontal page overflow at narrow widths.
- Remote text/key controls, quick actions, browser/page rows, and screen headers now wrap inside their cards instead of escaping the card padding.

## Validation

The package includes regression coverage for the runtime monitor wiring, persistent script registration, version synchronization, theme controls, and responsive containment.
