#!/usr/bin/env bash
set -u
host_name(){
  if command -v hostname >/dev/null 2>&1; then hostname 2>/dev/null && return; fi
  if [[ -r /proc/sys/kernel/hostname ]]; then cat /proc/sys/kernel/hostname && return; fi
  uname -n 2>/dev/null || echo unknown
}
printf '=== %s ===\n' "$(host_name)"
echo '-- health --'
if command -v curl >/dev/null 2>&1; then
  curl -fsS http://127.0.0.1:2324/api/health 2>/dev/null || echo 'WARN: agent health endpoint unavailable'
elif command -v wget >/dev/null 2>&1; then
  wget -qO- http://127.0.0.1:2324/api/health 2>/dev/null || echo 'WARN: agent health endpoint unavailable'
else
  echo 'WARN: curl/wget not installed; health endpoint not checked'
fi
echo
echo '-- doctor --'
kioskctl doctor --json || true
echo
echo '-- graphical session --'
if command -v systemctl >/dev/null 2>&1; then
  systemctl status getty@tty1.service --no-pager -l 2>&1 | tail -40 || true
  echo '-- kiosk session journal --'
  journalctl -t kioskctl-session -n 40 --no-pager -o cat 2>&1 || true
elif command -v rc-service >/dev/null 2>&1; then
  rc-service kioskctl-browser status 2>&1 || true
  echo '-- kiosk browser log --'
  tail -40 /var/log/kioskctl-browser.log 2>/dev/null || true
fi
echo
echo '-- wayland sockets --'
uid="$(id -u kioskctl 2>/dev/null || true)"
for d in "/run/user/${uid}" /run/kioskctl-user /run/kioskctl; do
  [[ -d "$d" ]] || continue
  printf '%s: ' "$d"
  find "$d" -maxdepth 1 -name 'wayland-*' -printf '%f ' 2>/dev/null || true
  echo
done
echo '-- processes --'
ps aux | grep -E '[c]age|[c]hromium|[k]ioskctl' || true
