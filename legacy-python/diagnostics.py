from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .browser import DevTools, browser_provider, browser_version, chromium_executable, resolved_user_data_dir
from .platform import WaylandTools, distro_info, init_system, input_devices, temperature_sensors, touch_mapping_status, touch_pointer_suppression_status, touchpad_suppression_status
from .session import enabled as kiosk_enabled


def _command_version(command: list[str]) -> str | None:
    try:
        p = subprocess.run(command, text=True, capture_output=True, timeout=4, check=False)
        text = (p.stdout or p.stderr).strip()
        return text.splitlines()[0] if text else None
    except Exception:
        return None


def _systemd_sessions(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    if init_system() != "systemd" or not shutil.which("loginctl"):
        return []
    user = str(cfg["system"]["kiosk_user"])
    found: list[dict[str, Any]] = []
    try:
        p = subprocess.run(["loginctl", "list-sessions", "--no-legend", "--no-pager"], text=True, capture_output=True, timeout=5, check=False)
        for line in p.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 6 and parts[2] == user:
                found.append({"session": parts[0], "uid": parts[1], "user": parts[2], "seat": parts[3], "leader": parts[4], "class": parts[5], "tty": parts[6] if len(parts) > 6 else ""})
    except Exception:
        pass
    return found


def _systemd_session(cfg: dict[str, Any]) -> dict[str, Any] | None:
    sessions = _systemd_sessions(cfg)
    # Prefer a real seat/TTY login over the persistent user-manager session.
    for session in sessions:
        if session.get("seat") not in ("", "-") or session.get("tty") not in ("", "-"):
            return session
    return sessions[0] if sessions else None


def _process_lines() -> list[str]:
    try:
        p = subprocess.run(["ps", "-eo", "user=,pid=,args="], text=True, capture_output=True, timeout=5, check=False)
        return [line.strip() for line in p.stdout.splitlines() if any(x in line for x in ("cage", "chromium", "kioskctl-session", "kioskctl-openrc-session"))][:24]
    except Exception:
        return []


def _session_log_tail() -> list[str]:
    if init_system() == "systemd" and shutil.which("journalctl"):
        try:
            p = subprocess.run(["journalctl", "-t", "kioskctl-session", "-n", "30", "--no-pager", "-o", "cat"], text=True, capture_output=True, timeout=5, check=False)
            return [x for x in p.stdout.splitlines() if x.strip()][-30:]
        except Exception:
            return []
    if init_system() == "openrc":
        path = Path("/var/log/kioskctl-browser.log")
        try:
            return path.read_text(errors="replace").splitlines()[-30:] if path.exists() else []
        except Exception:
            return []
    return []


def _openrc_browser_active() -> bool:
    if init_system() != "openrc" or not shutil.which("rc-service"):
        return False
    try:
        return subprocess.run(["rc-service", "kioskctl-browser", "status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0
    except Exception:
        return False



def _seatd_socket_ok(path: Path = Path("/run/seatd.sock")) -> bool:
    """Verify that the seatd path exists and is actually a Unix socket."""
    try:
        return path.exists() and path.is_socket()
    except OSError:
        return False

def diagnostic_report(cfg: dict[str, Any]) -> dict[str, Any]:
    dt = DevTools(int(cfg["browser"].get("devtools_port", 9222)), str(cfg["browser"].get("url", "")))
    tools = WaylandTools(cfg)
    try:
        executable = chromium_executable(str(cfg["browser"].get("executable", "auto")))
        provider = browser_provider(cfg)
        profile = str(resolved_user_data_dir(cfg))
    except Exception as exc:
        executable = str(cfg["browser"].get("executable", "auto"))
        provider = str(cfg["browser"].get("provider", "auto"))
        profile = str(cfg["browser"].get("user_data_dir", "auto"))
        browser_error = str(exc)
    else:
        browser_error = None

    devtools_version: dict[str, Any] | None = None
    try:
        devtools_version = dt.version()
    except Exception:
        pass
    try:
        viewport = dt.viewport_details() if devtools_version else None
    except Exception:
        viewport = None

    runtime = tools._runtime_dir()  # intentionally reported for diagnostics
    user = str(cfg["system"]["kiosk_user"])
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        uid = None
    outputs = tools.output_details()
    audio = tools.audio_status()
    sensors = temperature_sensors()
    inputs = input_devices()
    geometry = tools.geometry_status(viewport, outputs)
    touch_mapping = touch_mapping_status(cfg)
    touch_pointer = touch_pointer_suppression_status(cfg)
    touchpad = touchpad_suppression_status(cfg)
    init = init_system()
    sessions = _systemd_sessions(cfg)
    session = _systemd_session(cfg)

    checks = [
        {"id": "kiosk-user", "ok": uid is not None, "message": f"dedicated user {user}" if uid is not None else f"missing user {user}"},
        {"id": "runtime-dir", "ok": Path(runtime).exists(), "message": runtime},
        {"id": "browser-executable", "ok": bool(executable and executable != "auto" and Path(executable).exists()), "message": executable},
        {"id": "devtools", "ok": devtools_version is not None, "message": f"127.0.0.1:{cfg['browser'].get('devtools_port', 9222)}"},
        {"id": "wayland-output", "ok": bool(outputs), "message": ", ".join(str(x.get('name')) for x in outputs) if outputs else "no output detected"},
        {"id": "audio", "ok": bool(audio.get("available")), "message": str(audio.get("provider") or "no provider")},
        {"id": "temperature", "ok": bool(sensors), "message": str(sensors[0]["id"]) if sensors else "no sensor"},
    ]
    if touch_pointer.get("enabled") and touch_pointer.get("candidates"):
        total = len(touch_pointer.get("candidates") or [])
        active = int(touch_pointer.get("active_count") or 0)
        checks.append({
            "id": "touch-pointer",
            "ok": active == total,
            "message": f"{active}/{total} touchscreen compatibility pointer nodes ignored",
        })

    if touchpad.get("enabled") and touchpad.get("candidates"):
        total = len(touchpad.get("candidates") or [])
        active = int(touchpad.get("active_count") or 0)
        checks.append({
            "id": "touchpad",
            "ok": active == total,
            "message": f"{active}/{total} touchpad nodes ignored while kiosk is active",
        })

    if init == "systemd":
        checks.append({"id": "seat-session", "ok": bool(session and session.get("seat") not in ("", "-")), "message": json.dumps(session) if session else "no local kiosk session"})
    elif init == "openrc":
        checks.append({"id": "openrc-browser", "ok": _openrc_browser_active(), "message": "kioskctl-browser service"})
        checks.append({"id": "seatd", "ok": _seatd_socket_ok(), "message": "/run/seatd.sock"})

    return {
        "distro": distro_info(),
        "init_system": init,
        "kernel": os.uname().release,
        "kiosk_enabled": kiosk_enabled(cfg),
        "kiosk_user": {"name": user, "uid": uid},
        "session": session,
        "sessions": sessions,
        "runtime_dir": runtime,
        "browser": {
            "provider": provider,
            "executable": executable,
            "version": browser_version(executable) if executable and executable != "auto" else None,
            "profile": profile,
            "error": browser_error,
            "devtools": devtools_version,
            "viewport": viewport,
        },
        "display": {
            "outputs": outputs,
            "wayland_display": tools.wayland_display(),
            "runtime_dir": runtime,
            "geometry": geometry,
            "source": tools.display_source(),
            "wlr_randr": _command_version(["wlr-randr", "--version"]) or _command_version(["wlr-randr", "-v"]),
        },
        "cage": _command_version(["cage", "-v"]),
        "audio": audio,
        "temperature_sensors": sensors[:12],
        "input_devices": inputs,
        "touch_mapping": touch_mapping,
        "touch_pointer_suppression": touch_pointer,
        "touchpad_suppression": touchpad,
        "devices": {
            "dri": sorted(str(x) for x in Path("/dev/dri").glob("*") if x.is_char_device() or x.exists()) if Path("/dev/dri").exists() else [],
        },
        "processes": _process_lines(),
        "session_log_tail": _session_log_tail(),
        "checks": checks,
        "summary": {
            "ok": sum(1 for x in checks if x["ok"]),
            "warnings": sum(1 for x in checks if not x["ok"]),
        },
    }


def format_diagnostic_report(report: dict[str, Any]) -> str:
    lines = [
        "kioskctl diagnostics",
        "====================",
        f"OS:       {report['distro']['name']}",
        f"Init:     {report['init_system']}",
        f"Kernel:   {report['kernel']}",
        f"Kiosk:    {'enabled' if report['kiosk_enabled'] else 'disabled'}",
        f"Browser:  {report['browser']['provider']} — {report['browser']['version'] or report['browser']['executable']}",
        f"Audio:    {report['audio'].get('provider') or 'none'}",
        "",
        "Checks:",
    ]
    for check in report["checks"]:
        lines.append(f"  {'OK  ' if check['ok'] else 'WARN'} {check['id']}: {check['message']}")
    lines += ["", f"Summary: {report['summary']['ok']} OK, {report['summary']['warnings']} warnings"]
    return "\n".join(lines)
