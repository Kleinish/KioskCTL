from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from .config import DEFAULT_PATH, load_config
from .diagnostics import diagnostic_report, format_diagnostic_report
from .main import run, status
from .platform import WaylandTools
from .session import disable as disable_kiosk
from .session import enable as enable_kiosk
from .session import restart as restart_kiosk


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        command = exc.cmd if isinstance(exc.cmd, str) else " ".join(str(x) for x in exc.cmd)
        return f"command failed with exit status {exc.returncode}: {command}"
    return str(exc) or exc.__class__.__name__


def _dispatch(args: argparse.Namespace) -> None:
    if args.command == 'status':
        print(json.dumps(status(), indent=2))
    elif args.command == 'enable-kiosk':
        enable_kiosk()
        print('Kiosk mode enabled. Recovery: sudo kioskctl disable-kiosk')
    elif args.command == 'disable-kiosk':
        disable_kiosk()
        print('Kiosk mode disabled; normal console restored.')
    elif args.command == 'restart-kiosk':
        restart_kiosk()
        print('Kiosk session restarted.')
    elif args.command == 'reinitialize-display':
        print(json.dumps(WaylandTools(load_config()).reinitialize_display(), indent=2))
    elif args.command == 'doctor':
        report = diagnostic_report(load_config())
        print(json.dumps(report, indent=2) if args.json else format_diagnostic_report(report))
    elif args.command == 'uninstall':
        script = Path('/opt/kioskctl/uninstall.sh')
        if not script.exists():
            raise RuntimeError('installed uninstaller not found: /opt/kioskctl/uninstall.sh')
        cmd = [str(script)]
        if args.purge:
            cmd.append('--purge')
        if args.yes:
            cmd.append('--yes')
        subprocess.run(cmd, check=True)
    elif args.command == 'validate-config':
        print(json.dumps(load_config(Path(args.config)), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog='kioskctl')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('serve', help='Run the web/API agent')
    sub.add_parser('status', help='Print local status as JSON')
    sub.add_parser('enable-kiosk', help='Enable the graphical kiosk session')
    sub.add_parser('disable-kiosk', help='Disable kiosk mode and restore the normal console')
    sub.add_parser('restart-kiosk', help='Restart the graphical kiosk session')
    sub.add_parser('reinitialize-display', help='Power-cycle/reapply the configured Wayland display mode')
    uninstall = sub.add_parser('uninstall', help='Remove kioskctl; use --purge for a pristine-development reset')
    uninstall.add_argument('--purge', action='store_true', help='Remove kioskctl configuration, browser profile, dedicated user, policies and runtime state')
    uninstall.add_argument('--yes', '-y', action='store_true', help='Do not prompt for purge confirmation')
    doctor = sub.add_parser('doctor', help='Cross-distro diagnostic report; ideal for multi-exec')
    doctor.add_argument('--json', action='store_true', help='Emit machine-readable JSON')
    validate = sub.add_parser('validate-config', help='Validate and print merged configuration')
    validate.add_argument('--config', default=str(DEFAULT_PATH))
    args = parser.parse_args()

    # Keep the long-running server path transparent to systemd/OpenRC so a
    # startup failure retains its normal traceback in service logs.
    if args.command == 'serve':
        run()
        return

    try:
        _dispatch(args)
    except KeyboardInterrupt:
        parser.exit(130, 'kioskctl: interrupted\n')
    except Exception as exc:
        # Developers can opt back into a full traceback while field users get a
        # concise error suitable for terminals and remote-exec tools.
        if os.environ.get('KIOSKCTL_DEBUG', '').lower() in {'1', 'true', 'yes'}:
            raise
        parser.exit(1, f'kioskctl: error: {_friendly_error(exc)}\n')


if __name__ == '__main__':
    main()
