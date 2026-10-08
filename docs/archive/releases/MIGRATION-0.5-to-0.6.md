# Migrating v0.5.2 to v0.6

1. Back up `/etc/kioskctl` and `/var/lib/kioskctl`.
2. Stop the v0.5 agent, extract v0.6, and run `sudo ./install.sh`.
3. Schema 10 migrates to 11 in memory; the first settings save persists it.
4. Run `sudo kioskctl doctor`; verify browser, display, MQTT, Home Assistant, and screensavers.
5. Test Immich portrait/landscape originals and HEIC/RAW in both fit modes.

The installer retains `/opt/kioskctl.backup-TIMESTAMP` and a config backup. Roll back with `sudo scripts/rollback-0.6.sh /opt/kioskctl.backup-TIMESTAMP`. Restore the matching schema-10 config backup before starting v0.5.2.
