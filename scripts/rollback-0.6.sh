#!/bin/sh
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
BACKUP=${1:-}; [ -n "$BACKUP" ] && [ -d "$BACKUP" ] || { echo "Usage: sudo $0 /opt/kioskctl.backup-TIMESTAMP" >&2; exit 2; }
systemctl stop kioskctl-agent.service 2>/dev/null || true
mv /opt/kioskctl "/opt/kioskctl.failed-$(date +%Y%m%d-%H%M%S)"; cp -a "$BACKUP" /opt/kioskctl
systemctl daemon-reload 2>/dev/null || true; systemctl start kioskctl-agent.service 2>/dev/null || true
