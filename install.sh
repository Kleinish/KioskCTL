#!/bin/sh
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo ./install.sh" >&2; exit 1; }
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET=${KIOSKCTL_TARGET:-/opt/kioskctl}
BIN=${KIOSKCTL_BINARY:-$ROOT/target/release/kioskctl}
if [ ! -x "$BIN" ]; then command -v cargo >/dev/null 2>&1 || { echo "Rust 1.88+ is required, or set KIOSKCTL_BINARY." >&2; exit 1; }; (cd "$ROOT" && cargo build --release); fi
getent group kioskctl >/dev/null 2>&1 || groupadd --system kioskctl
id kioskctl >/dev/null 2>&1 || useradd --system --gid kioskctl --home-dir /var/lib/kioskctl --create-home --shell /usr/sbin/nologin kioskctl
for group in seat video render input audio; do
  getent group "$group" >/dev/null 2>&1 && usermod -a -G "$group" kioskctl
done
STAMP=$(date +%Y%m%d-%H%M%S)
[ ! -d "$TARGET" ] || cp -a "$TARGET" "${TARGET}.backup-${STAMP}"
[ ! -f /etc/kioskctl/config.yaml ] || cp -a /etc/kioskctl/config.yaml "/etc/kioskctl/config.yaml.backup-${STAMP}"
install -d -m 0755 "$TARGET/web" "$TARGET/scripts" /etc/kioskctl/plugins.d /var/lib/kioskctl/screensaver /var/lib/kioskctl/plugins /run/kioskctl
install -m 0755 "$BIN" /usr/local/bin/kioskctl
cp -a "$ROOT/web/." "$TARGET/web/"; cp -a "$ROOT/scripts/." "$TARGET/scripts/"
if [ ! -f /etc/kioskctl/config.yaml ]; then install -m 0640 -o root -g kioskctl "$ROOT/examples/config.yaml" /etc/kioskctl/config.yaml; fi
/usr/local/bin/kioskctl --config /etc/kioskctl/config.yaml check-config
if command -v systemctl >/dev/null 2>&1; then install -m 0644 "$ROOT/systemd/kioskctl-agent.service" /etc/systemd/system/; install -m 0644 "$ROOT/systemd/kioskctl-browser.service" /etc/systemd/system/; systemctl daemon-reload; systemctl enable --now kioskctl-agent.service; systemctl enable --now kioskctl-browser.service; elif command -v rc-update >/dev/null 2>&1; then install -m 0755 "$ROOT/openrc/kioskctl-agent" /etc/init.d/kioskctl-agent; install -m 0755 "$ROOT/openrc/kioskctl-browser" /etc/init.d/kioskctl-browser; rc-update add kioskctl-agent default; rc-update add kioskctl-browser default; rc-service kioskctl-agent restart; rc-service kioskctl-browser restart; else echo "Installed; configure your service manager manually."; fi
echo "kioskctl 0.6.0 installed. Backup suffix: $STAMP"
