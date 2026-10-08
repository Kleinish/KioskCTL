from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .config import load_config
from .platform import init_system, install_touchpad_suppression

OVERRIDE_DIR = Path('/etc/systemd/system/getty@tty1.service.d')
OVERRIDE_PATH = OVERRIDE_DIR / 'kioskctl-autologin.conf'
TEMPLATE_PATH = Path('/opt/kioskctl/systemd/getty@tty1.service.d/kioskctl-autologin.conf')
OPENRC_SERVICE = 'kioskctl-browser'


def _require_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError('This action must be run as root (use sudo).')


def enabled(cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or load_config()
    marker = Path(str(cfg['system'].get('enabled_marker', '/etc/kioskctl/kiosk.enabled')))
    if not marker.exists():
        return False
    init = init_system()
    if init == 'systemd':
        return OVERRIDE_PATH.exists()
    if init == 'openrc':
        return True
    return False


def _restorecon(*paths: Path) -> None:
    restorecon = shutil.which('restorecon')
    if not restorecon:
        return
    try:
        subprocess.run(
            [restorecon, '-F', *[str(p) for p in paths]],
            check=False,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('restorecon timed out while applying SELinux labels') from exc


def _install_systemd_override() -> None:
    """Install the tty1 drop-in without preserving source SELinux xattrs.

    Fedora is SELinux-enforcing and shutil.copy2() can preserve extended
    attributes from /opt onto a file under /etc/systemd/system.  Write the
    file afresh, then restore the target path's policy label.
    """
    OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f'Missing getty template: {TEMPLATE_PATH}')

    content = TEMPLATE_PATH.read_text(encoding='utf-8')
    fd, tmp_name = tempfile.mkstemp(prefix='.kioskctl-autologin-', dir=str(OVERRIDE_DIR))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, OVERRIDE_PATH)
    finally:
        tmp.unlink(missing_ok=True)
    _restorecon(OVERRIDE_DIR, OVERRIDE_PATH)


def _getty_has_autologin() -> bool:
    p = subprocess.run(
        ['systemctl', 'show', 'getty@tty1.service', '-p', 'ExecStart', '--value'],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    return p.returncode == 0 and '--autologin kioskctl' in p.stdout


def _restart_systemd_getty() -> None:
    # getty@tty1 is normally generator/static managed. `systemctl enable` is
    # unnecessary and Fedora can reject it with "Access denied".
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'unmask', 'getty@tty1.service'], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['systemctl', 'reset-failed', 'getty@tty1.service'], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Fedora 44 exposed a case where systemd still had the previous getty
    # definition cached after the drop-in changed. Verify before restarting.
    # daemon-reexec is used only as a fallback and keeps running services alive.
    if not _getty_has_autologin():
        subprocess.run(['systemctl', 'daemon-reexec'], check=False)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'reset-failed', 'getty@tty1.service'], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not _getty_has_autologin():
        raise RuntimeError(
            'systemd did not load the kioskctl tty1 autologin drop-in. '
            'Run: systemctl status getty@tty1.service && ls -lZ '
            '/etc/systemd/system/getty@tty1.service.d/'
        )

    p = subprocess.run(['systemctl', 'restart', 'getty@tty1.service'], check=False)
    if p.returncode != 0:
        subprocess.run(['systemctl', 'reset-failed', 'getty@tty1.service'], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['systemctl', 'start', 'getty@tty1.service'], check=True)


def enable() -> None:
    _require_root()
    cfg = load_config()
    marker = Path(str(cfg['system'].get('enabled_marker', '/etc/kioskctl/kiosk.enabled')))
    init = init_system()
    marker.parent.mkdir(parents=True, exist_ok=True)

    # Apply the kiosk-only touchpad preference before Cage opens libinput.
    # This is reversible and is automatically removed by disable().
    install_touchpad_suppression(cfg, reload_rules=True)

    if init == 'systemd':
        _install_systemd_override()
        marker.touch(mode=0o644, exist_ok=True)
        _restorecon(marker)
        _restart_systemd_getty()
        return

    if init == 'openrc':
        marker.touch(mode=0o644, exist_ok=True)
        if shutil.which('rc-update'):
            subprocess.run(['rc-update', 'add', OPENRC_SERVICE, 'default'], check=False)
        subprocess.run(['rc-service', OPENRC_SERVICE, 'stop'], check=False)
        subprocess.run(['rc-service', OPENRC_SERVICE, 'start'], check=True)
        return

    raise RuntimeError('Unsupported init system')


def disable() -> None:
    _require_root()
    cfg = load_config()
    marker = Path(str(cfg['system'].get('enabled_marker', '/etc/kioskctl/kiosk.enabled')))
    init = init_system()
    marker.unlink(missing_ok=True)

    # Restore the touchpad for the normal console without forgetting the kiosk
    # preference stored in config. The following getty/OpenRC transition reopens
    # input devices so libinput sees the restored node.
    install_touchpad_suppression(cfg, reload_rules=True, force_enabled=False)

    if init == 'systemd':
        OVERRIDE_PATH.unlink(missing_ok=True)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'restart', 'getty@tty1.service'], check=True)
        return

    if init == 'openrc':
        subprocess.run(['rc-service', OPENRC_SERVICE, 'stop'], check=False)
        if shutil.which('rc-update'):
            subprocess.run(['rc-update', 'del', OPENRC_SERVICE, 'default'], check=False)
        return

    raise RuntimeError('Unsupported init system')


def restart() -> None:
    _require_root()
    if not enabled():
        raise RuntimeError('Kiosk mode is disabled. Run: sudo kioskctl enable-kiosk')
    init = init_system()
    if init == 'systemd':
        _restart_systemd_getty()
        return
    if init == 'openrc':
        subprocess.run(['rc-service', OPENRC_SERVICE, 'restart'], check=True)
        return
    raise RuntimeError('Unsupported init system')
