#!/bin/sh
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
systemctl disable --now kioskctl-agent.service kioskctl-browser.service 2>/dev/null || true
rm -f /etc/systemd/system/kioskctl-agent.service /etc/systemd/system/kioskctl-browser.service
rc-service kioskctl-agent stop 2>/dev/null || true
rc-update del kioskctl-agent default 2>/dev/null || true
rm -f /etc/init.d/kioskctl-agent /usr/local/bin/kioskctl
systemctl daemon-reload 2>/dev/null || true
echo "Binary and services removed. Configuration and data were preserved in /etc/kioskctl and /var/lib/kioskctl."
