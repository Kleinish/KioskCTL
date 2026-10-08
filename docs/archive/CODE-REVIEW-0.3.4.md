# v0.3.4 external code-review follow-up

The 0.3.6 hardening release addresses the actionable findings from an external review of 0.3.4.

| Finding | 0.3.6 disposition |
|---|---|
| `restorecon` could wait forever | Fixed: 10-second timeout; timeout becomes a clear RuntimeError |
| seatd diagnostic accepted any existing path | Fixed: requires both `exists()` and `is_socket()` |
| DevTools port lacked range validation | Fixed centrally; browser/admin/MQTT ports must be 1-65535 |
| config version was silently forced to v3 | Fixed: explicit v1/v2 -> v3 migration and future-schema rejection |
| display fixup silently ended if DevTools stayed unavailable | Fixed: explicit warning is written to the graphical-session log |
| CLI emitted tracebacks for normal field errors | Fixed: concise errors by default; `KIOSKCTL_DEBUG=1` restores traceback behavior |
| notification enums differ between policy and Preferences | Documented in code; the different values are intentional for the two Chromium formats |

The review also repeated the seatd and config-migration findings in separate sections; they are handled once in the implementation.

No tty/logind/Cage startup behavior was changed in 0.3.6.
