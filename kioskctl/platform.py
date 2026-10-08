from __future__ import annotations

import json
import os
import platform
import pwd
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def distro_info() -> dict[str, str]:
    data: dict[str, str] = {}
    p = Path("/etc/os-release")
    if p.exists():
        for line in p.read_text(errors="ignore").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.lower()] = v.strip().strip('"')
    return {
        "id": data.get("id", "unknown"),
        "name": data.get("pretty_name", data.get("name", "Linux")),
        "id_like": data.get("id_like", ""),
    }


def init_system() -> str:
    if shutil.which("systemctl") and Path("/run/systemd/system").exists():
        return "systemd"
    if shutil.which("rc-service"):
        return "openrc"
    return "unknown"


def _cpu_sample() -> tuple[int, int]:
    fields = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    return sum(fields), idle


def _cpu_percent() -> float:
    try:
        total1, idle1 = _cpu_sample()
        time.sleep(0.05)
        total2, idle2 = _cpu_sample()
        dt, di = total2 - total1, idle2 - idle1
        return round((1 - di / dt) * 100, 1) if dt else 0.0
    except Exception:
        return 0.0


def _memory_percent() -> float:
    try:
        vals: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                vals[k] = int(v.strip().split()[0])
        total = vals["MemTotal"]
        avail = vals.get("MemAvailable", vals.get("MemFree", 0))
        return round((1 - avail / total) * 100, 1)
    except Exception:
        return 0.0


def _read_temp(path: Path) -> float | None:
    try:
        value = float(path.read_text().strip())
        if abs(value) > 1000:
            value /= 1000.0
        if -20 < value < 150:
            return round(value, 1)
    except Exception:
        pass
    return None


def temperature_sensors() -> list[dict[str, Any]]:
    sensors: list[dict[str, Any]] = []
    cpu_names = {"coretemp": 110, "k10temp": 110, "zenpower": 105, "cpu_thermal": 105, "soc_thermal": 90, "acpitz": 60}
    non_cpu_names = {"nvme", "iwlwifi", "amdgpu", "radeon", "drivetemp", "battery"}

    for hw in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            name = (hw / "name").read_text().strip().lower()
        except Exception:
            name = hw.name.lower()
        for input_path in sorted(hw.glob("temp*_input")):
            value = _read_temp(input_path)
            if value is None:
                continue
            stem = input_path.name[:-6]  # temp1_ from temp1_input
            label_path = hw / f"{stem}_label"
            try:
                label = label_path.read_text().strip()
            except Exception:
                label = input_path.name.replace("_input", "")
            lname = label.lower()
            score = cpu_names.get(name, 20)
            if name in non_cpu_names:
                score = 0
            if "package" in lname:
                score += 40
            if "tctl" in lname or "tdie" in lname:
                score += 35
            if "cpu" in lname:
                score += 30
            if "core" in lname:
                score += 12
            if "edge" in lname or "junction" in lname or "composite" in lname:
                score -= 15
            sensors.append({
                "id": f"hwmon:{name}:{label}",
                "source": "hwmon",
                "chip": name,
                "label": label,
                "value_c": value,
                "score": score,
                "path": str(input_path),
            })

    # Thermal zones are a fallback for systems where hwmon is sparse (common on
    # ARM/SBCs and some Alpine installs). They are ranked rather than taking the
    # first zone, which caused incorrect CPU temperatures in V0.2.
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        value = _read_temp(zone / "temp")
        if value is None:
            continue
        try:
            ztype = (zone / "type").read_text().strip()
        except Exception:
            ztype = zone.name
        ltype = ztype.lower()
        score = 25
        if any(x in ltype for x in ("x86_pkg_temp", "cpu", "soc", "package")):
            score = 85
        if any(x in ltype for x in ("iwlwifi", "wifi", "nvme", "gpu", "battery")):
            score = 0
        sensors.append({
            "id": f"thermal:{ztype}",
            "source": "thermal",
            "chip": ztype,
            "label": ztype,
            "value_c": value,
            "score": score,
            "path": str(zone / "temp"),
        })

    # Prefer high confidence CPU sources, then stable label/id ordering.
    sensors.sort(key=lambda x: (-int(x["score"]), str(x["id"])))
    return sensors



def _udev_event_properties(event: str | None) -> dict[str, str]:
    """Read udev properties for an event device without spawning udevadm.

    systemd-udevd/eudev persist properties under /run/udev/data.  Reading that
    cache is cheap enough for the status endpoint and lets us correctly
    identify integrated Wacom/ELAN touch devices whose product names do not
    contain the word "touchscreen".
    """
    if not event:
        return {}
    device = Path('/dev/input') / event
    try:
        st = device.stat()
        key = f"c{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"
        data_path = Path('/run/udev/data') / key
        props: dict[str, str] = {}
        for line in data_path.read_text(errors='replace').splitlines():
            if line.startswith('E:') and '=' in line[2:]:
                k, v = line[2:].split('=', 1)
                props[k] = v
        return props
    except Exception:
        return {}


def input_devices() -> list[dict[str, Any]]:
    """Return Linux input inventory with optional udev classification.

    /proc/bus/input/devices remains the portable baseline.  When udev metadata
    is available we use ID_INPUT_* properties to distinguish touchscreen,
    touchpad and tablet devices more accurately than product-name heuristics.
    """
    path = Path('/proc/bus/input/devices')
    if not path.exists():
        return []
    devices: list[dict[str, Any]] = []
    try:
        blocks = path.read_text(errors='replace').strip().split('\n\n')
    except Exception:
        return []
    for block in blocks:
        if not block.strip():
            continue
        name_match = re.search(r'^N: Name="(.*)"$', block, re.M)
        handlers_match = re.search(r'^H: Handlers=(.*)$', block, re.M)
        phys_match = re.search(r'^P: Phys=(.*)$', block, re.M)
        sysfs_match = re.search(r'^S: Sysfs=(.*)$', block, re.M)
        name = name_match.group(1) if name_match else 'Unknown input device'
        handlers = handlers_match.group(1).split() if handlers_match else []
        event = next((h for h in handlers if h.startswith('event')), None)
        props = _udev_event_properties(event)
        lower = name.lower()
        dtype = 'other'
        if props.get('ID_INPUT_TOUCHSCREEN') == '1':
            dtype = 'touchscreen'
        elif props.get('ID_INPUT_TOUCHPAD') == '1':
            dtype = 'touchpad'
        elif props.get('ID_INPUT_TABLET') == '1' or props.get('ID_INPUT_TABLET_TOOL') == '1':
            dtype = 'tablet'
        elif props.get('ID_INPUT_KEYBOARD') == '1':
            dtype = 'keyboard'
        elif props.get('ID_INPUT_MOUSE') == '1':
            dtype = 'mouse'
        elif 'touchscreen' in lower or 'touch screen' in lower:
            dtype = 'touchscreen'
        elif 'touchpad' in lower or 'trackpad' in lower:
            dtype = 'touchpad'
        elif any(x in lower for x in ('wacom', 'stylus', 'tablet', 'pen')):
            dtype = 'tablet'
        elif 'kbd' in handlers:
            dtype = 'keyboard'
        elif any(h.startswith('mouse') for h in handlers):
            dtype = 'mouse'
        devices.append({
            'name': name,
            'type': dtype,
            'event': event,
            'handlers': handlers,
            'phys': phys_match.group(1) if phys_match else '',
            'sysfs': sysfs_match.group(1) if sysfs_match else '',
            'udev': {k: v for k, v in props.items() if k.startswith('ID_INPUT_') or k in {'LIBINPUT_CALIBRATION_MATRIX','LIBINPUT_IGNORE_DEVICE'}},
        })
    return devices


TOUCH_POINTER_RULE_PATH = Path('/etc/udev/rules.d/99-kioskctl-touch-pointer.rules')

def _touch_pointer_candidates() -> list[dict[str, Any]]:
    """Return mouse-capability event nodes that belong to a touchscreen device.

    Many laptop/tablet digitizers expose both a touchscreen event node and a
    compatibility mouse node with the same physical device identifier. Cage/wlroots
    sees that compatibility node as a real pointer and keeps a hardware cursor alive
    even on touch-only interaction. Ignore only those paired compatibility nodes;
    real USB mice and touchpads remain available.
    """
    devices = input_devices()
    touch_phys = {str(d.get('phys') or '') for d in devices if d.get('type') == 'touchscreen' and d.get('phys')}
    return [d for d in devices if d.get('type') == 'mouse' and d.get('phys') in touch_phys and d.get('event')]


def touch_pointer_suppression_status(cfg: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(cfg.get('input', {}).get('ignore_touch_mouse_emulation', True))
    candidates = _touch_pointer_candidates()
    active = {str(d.get('event')): d.get('udev', {}).get('LIBINPUT_IGNORE_DEVICE') for d in candidates}
    return {
        'enabled': enabled,
        'rule_path': str(TOUCH_POINTER_RULE_PATH),
        'rule_installed': TOUCH_POINTER_RULE_PATH.exists(),
        'candidates': candidates,
        'active': active,
        'active_count': sum(1 for v in active.values() if str(v) == '1'),
    }


def install_touch_pointer_suppression(cfg: dict[str, Any], reload_rules: bool = True) -> dict[str, Any]:
    """Ignore touchscreen-generated compatibility mouse nodes in libinput.

    This is intentionally narrower than hiding every mouse cursor: only mouse event
    nodes sharing the same Phys= identifier as a detected touchscreen are ignored.
    Touchpads and independently attached mice continue to work normally.
    """
    enabled = bool(cfg.get('input', {}).get('ignore_touch_mouse_emulation', True))
    candidates = _touch_pointer_candidates()
    if os.geteuid() != 0:
        return {**touch_pointer_suppression_status(cfg), 'changed': False, 'warning': 'root is required to update touch pointer suppression'}

    previous = TOUCH_POINTER_RULE_PATH.read_text(errors='replace') if TOUCH_POINTER_RULE_PATH.exists() else ''
    if not enabled or not candidates:
        TOUCH_POINTER_RULE_PATH.unlink(missing_ok=True)
        changed = bool(previous)
    else:
        TOUCH_POINTER_RULE_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            '# Managed by kioskctl. Ignore touchscreen-emulated compatibility mouse nodes.',
            '# Real mice and touchpads are not matched by this rule.',
        ]
        seen: set[str] = set()
        for dev in candidates:
            phys = str(dev.get('phys') or '')
            if not phys or phys in seen:
                continue
            seen.add(phys)
            esc = phys.replace('\\', '\\\\').replace('\"', '\\"')
            lines.append(
                'ACTION!="remove", KERNEL=="event*", ENV{ID_INPUT_MOUSE}=="1", '
                f'ATTRS{{phys}}=="{esc}", ENV{{LIBINPUT_IGNORE_DEVICE}}="1"'
            )
        content = '\n'.join(lines) + '\n'
        TOUCH_POINTER_RULE_PATH.write_text(content)
        os.chmod(TOUCH_POINTER_RULE_PATH, 0o644)
        changed = previous != content

    warning = None
    udevadm = shutil.which('udevadm')
    if reload_rules and udevadm:
        try:
            subprocess.run([udevadm, 'control', '--reload-rules'], check=True, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            for dev in candidates:
                event = dev.get('event')
                if event:
                    subprocess.run([udevadm, 'trigger', '--action=change', '--subsystem-match=input', '--sysname-match', str(event)], check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            warning = f'udev reload failed: {exc}'
    elif reload_rules and enabled and candidates:
        warning = 'udevadm is unavailable; pointer suppression will activate after reboot/session device reprobe'

    result = touch_pointer_suppression_status(cfg)
    result['changed'] = changed
    result['udevadm_available'] = bool(udevadm)
    if warning:
        result['warning'] = warning
    return result


TOUCHPAD_RULE_PATH = Path('/etc/udev/rules.d/99-kioskctl-touchpad.rules')

def _touchpad_candidates() -> list[dict[str, Any]]:
    """Return libinput touchpad event nodes.

    Some touchscreen laptops continuously expose a fine pointer through the
    built-in touchpad. wlroots/Cage quite reasonably treats that as a mouse
    source, which means a hardware cursor can remain visible on an otherwise
    touch-first kiosk. kioskctl can optionally ignore the touchpad while kiosk
    mode is active; the touchscreen, stylus, keyboard and external mice are not
    matched by this rule.
    """
    return [d for d in input_devices() if d.get('type') == 'touchpad' and d.get('event')]


def touchpad_suppression_status(cfg: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(cfg.get('input', {}).get('disable_touchpad_in_kiosk', False))
    candidates = _touchpad_candidates()
    active = {str(d.get('event')): d.get('udev', {}).get('LIBINPUT_IGNORE_DEVICE') for d in candidates}
    return {
        'enabled': enabled,
        'rule_path': str(TOUCHPAD_RULE_PATH),
        'rule_installed': TOUCHPAD_RULE_PATH.exists(),
        'candidates': candidates,
        'active': active,
        'active_count': sum(1 for v in active.values() if str(v) == '1'),
    }


def install_touchpad_suppression(
    cfg: dict[str, Any],
    reload_rules: bool = True,
    force_enabled: bool | None = None,
) -> dict[str, Any]:
    """Optionally ignore built-in touchpad event nodes in libinput.

    This is meant for touch-first kiosks where the laptop touchpad keeps a
    compositor cursor alive. The setting is reversible: removing the rule and
    restarting/reopening the kiosk session restores the touchpad.  `force_enabled`
    is used by kiosk disable/enable so the touchpad is restored outside kiosk mode
    without forgetting the user's kiosk preference.
    """
    configured = bool(cfg.get('input', {}).get('disable_touchpad_in_kiosk', False))
    enabled = configured if force_enabled is None else bool(force_enabled and configured)
    candidates = _touchpad_candidates()
    if os.geteuid() != 0:
        result = touchpad_suppression_status(cfg)
        result['effective_enabled'] = enabled
        result['changed'] = False
        result['warning'] = 'root is required to update touchpad suppression'
        return result

    previous = TOUCHPAD_RULE_PATH.read_text(errors='replace') if TOUCHPAD_RULE_PATH.exists() else ''
    if not enabled:
        TOUCHPAD_RULE_PATH.unlink(missing_ok=True)
        changed = bool(previous)
    else:
        TOUCHPAD_RULE_PATH.parent.mkdir(parents=True, exist_ok=True)
        content = '\n'.join([
            '# Managed by kioskctl. Disable touchpads while graphical kiosk mode is active.',
            '# Touchscreens, tablets/styluses, keyboards and external mice are not matched.',
            'ACTION!="remove", KERNEL=="event*", ENV{ID_INPUT_TOUCHPAD}=="1", ENV{LIBINPUT_IGNORE_DEVICE}="1"',
            '',
        ])
        TOUCHPAD_RULE_PATH.write_text(content)
        os.chmod(TOUCHPAD_RULE_PATH, 0o644)
        changed = previous != content

    warning = None
    udevadm = shutil.which('udevadm')
    if reload_rules and udevadm:
        try:
            subprocess.run([udevadm, 'control', '--reload-rules'], check=True, timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            # Trigger all known touchpad nodes so diagnostics can see the property
            # immediately. Cage/libinput still needs the graphical session restart
            # performed by the API/session layer to reopen the device.
            for dev in candidates:
                event = dev.get('event')
                if event:
                    subprocess.run([udevadm, 'trigger', '--action=change', '--subsystem-match=input',
                                    '--sysname-match', str(event)], check=False, timeout=5,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            warning = f'udev reload failed: {exc}'
    elif reload_rules and enabled and candidates:
        warning = 'udevadm is unavailable; touchpad suppression will activate after reboot/session device reprobe'

    result = touchpad_suppression_status(cfg)
    result['effective_enabled'] = enabled
    result['changed'] = changed
    result['udevadm_available'] = bool(udevadm)
    if warning:
        result['warning'] = warning
    return result


TOUCH_RULE_PATH = Path('/etc/udev/rules.d/99-kioskctl-touch.rules')
_TOUCH_MATRICES: dict[str, str] = {
    # libinput uses a 2x3 affine matrix: x' = ax + by + c, y' = dx + ey + f.
    # wlroots/wlr-randr transform names follow wl_output transforms.  The input
    # matrix is the inverse transform needed to map physical panel coordinates
    # back into the compositor's logical coordinate space.
    'normal': '1 0 0 0 1 0',
    '90': '0 -1 1 1 0 0',
    '180': '-1 0 1 0 -1 1',
    '270': '0 1 0 -1 0 1',
}


def touch_calibration_matrix(transform: str) -> str | None:
    return _TOUCH_MATRICES.get(str(transform))


def touch_mapping_status(cfg: dict[str, Any]) -> dict[str, Any]:
    devices = [d for d in input_devices() if d.get('type') == 'touchscreen']
    enabled = bool(cfg.get('input', {}).get('rotate_touch_with_display', True))
    transform = str(cfg.get('display', {}).get('transform', 'normal'))
    matrix = touch_calibration_matrix(transform) if enabled else None
    active = {
        str(d.get('event')): d.get('udev', {}).get('LIBINPUT_CALIBRATION_MATRIX')
        for d in devices if d.get('event')
    }
    return {
        'enabled': enabled,
        'transform': transform,
        'matrix': matrix,
        'rule_path': str(TOUCH_RULE_PATH),
        'rule_installed': TOUCH_RULE_PATH.exists(),
        'touchscreens': devices,
        'active_matrices': active,
        'supported': matrix is not None or not enabled,
    }


def install_touch_transform(cfg: dict[str, Any], reload_rules: bool = True) -> dict[str, Any]:
    """Persist libinput calibration so physical touch follows screen rotation.

    libinput reads LIBINPUT_CALIBRATION_MATRIX when the input device is added.
    We reload/trigger udev here; callers that change the transform at runtime
    should also restart the Cage session so already-open libinput devices are
    guaranteed to pick up the new matrix.
    """
    enabled = bool(cfg.get('input', {}).get('rotate_touch_with_display', True))
    transform = str(cfg.get('display', {}).get('transform', 'normal'))
    matrix = touch_calibration_matrix(transform) if enabled else None

    if os.geteuid() != 0:
        return {**touch_mapping_status(cfg), 'changed': False, 'warning': 'root is required to update touch calibration'}

    if not enabled:
        try:
            TOUCH_RULE_PATH.unlink(missing_ok=True)
        except Exception as exc:
            return {**touch_mapping_status(cfg), 'changed': False, 'warning': str(exc)}
    elif matrix is None:
        return {**touch_mapping_status(cfg), 'changed': False, 'warning': f'No automatic touch matrix for transform {transform!r}'}
    else:
        TOUCH_RULE_PATH.parent.mkdir(parents=True, exist_ok=True)
        content = (
            '# Managed by kioskctl. Physical touchscreen coordinates follow display rotation.\n'
            '# libinput opens /dev/input/event* nodes, so apply the property to those\n'
            '# exact udev devices rather than only their parent input nodes.\n'
            'ACTION!="remove", KERNEL=="event*", ENV{ID_INPUT_TOUCHSCREEN}=="1", '
            f'ENV{{LIBINPUT_CALIBRATION_MATRIX}}="{matrix}"\n'
        )
        previous = TOUCH_RULE_PATH.read_text(errors='replace') if TOUCH_RULE_PATH.exists() else ''
        TOUCH_RULE_PATH.write_text(content)
        os.chmod(TOUCH_RULE_PATH, 0o644)
        changed = previous != content

    warning = None
    udevadm = shutil.which('udevadm')
    if reload_rules and udevadm:
        try:
            subprocess.run([udevadm, 'control', '--reload-rules'], check=True, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            # Trigger the touchscreen event devices directly. This matters on
            # Alpine/eudev where a broad subsystem change did not reliably
            # refresh LIBINPUT_CALIBRATION_MATRIX before Cage reopened them.
            touches = [d for d in input_devices() if d.get('type') == 'touchscreen']
            for device in touches:
                event = device.get('event')
                if not event:
                    continue
                triggered = subprocess.run(
                    [udevadm, 'trigger', '--action=change', '--subsystem-match=input', '--sysname-match', str(event)],
                    check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                if triggered.returncode != 0:
                    # eudev/systemd-udev versions differ slightly in trigger
                    # filtering support. Fall back to the portable broad input
                    # trigger rather than leaving a freshly-written rule idle.
                    subprocess.run([udevadm, 'trigger', '--subsystem-match=input', '--action=change'], check=False, timeout=8, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            warning = f'udev reload failed: {exc}'
    elif reload_rules and enabled and matrix is not None:
        warning = 'udevadm is unavailable; touch calibration rule was saved but cannot be activated until udev reloads'

    result = touch_mapping_status(cfg)
    result['changed'] = locals().get('changed', True)
    result['udevadm_available'] = bool(udevadm)
    active: dict[str, str | None] = {}
    if udevadm:
        for device in result.get('touchscreens', []):
            event = device.get('event')
            if not event:
                continue
            try:
                p = subprocess.run([udevadm, 'info', '--query=property', f'/dev/input/{event}'], check=False, text=True, capture_output=True, timeout=4)
                value = None
                for line in p.stdout.splitlines():
                    if line.startswith('LIBINPUT_CALIBRATION_MATRIX='):
                        value = line.split('=', 1)[1].strip()
                        break
                active[str(event)] = value
            except Exception:
                active[str(event)] = None
    result['active_matrices'] = active
    if warning:
        result['warning'] = warning
    elif enabled and matrix is not None and active and any(v != matrix for v in active.values()):
        result['warning'] = 'touch calibration rule is installed but one or more touchscreen event devices have not picked up the matrix yet'
    return result


def primary_temperature(cfg: dict[str, Any] | None = None) -> tuple[float | None, str | None]:
    sensors = temperature_sensors()
    if not sensors:
        return None, None
    requested = str((cfg or {}).get("temperature", {}).get("primary", "auto"))
    if requested and requested != "auto":
        for sensor in sensors:
            if sensor["id"] == requested:
                return float(sensor["value_c"]), str(sensor["id"])
    # Only call a sensor "CPU" if its score indicates reasonable confidence.
    best = sensors[0]
    if int(best["score"]) <= 0:
        return None, None
    return float(best["value_c"]), str(best["id"])


def system_metrics(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        uptime = int(float(Path("/proc/uptime").read_text().split()[0]))
    except Exception:
        uptime = 0
    disk = shutil.disk_usage("/")
    temp, temp_sensor = primary_temperature(cfg)
    return {
        "hostname": platform.node(),
        "kernel": platform.release(),
        "uptime_seconds": uptime,
        "cpu_percent": _cpu_percent(),
        "memory_percent": _memory_percent(),
        "disk_percent": round((disk.used / disk.total) * 100, 1) if disk.total else 0.0,
        "temperature_c": temp,
        "temperature_sensor": temp_sensor,
    }


class WaylandTools:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self._detected_wayland_display: str | None = None
        self._detected_runtime_dir: str | None = None
        self._display_source: str = "none"

    def _runtime_dirs(self) -> list[str]:
        """Return plausible kiosk runtime directories in preference order.

        Older Alpine configs used /run/kioskctl while the OpenRC graphical
        launcher has always used /run/kioskctl-user.  Do not let a preserved
        legacy value hide the live compositor socket; probe all safe runtime
        locations and remember the one that actually answers.
        """
        s = self.cfg["system"]
        configured = str(s.get("runtime_dir", "auto") or "auto")
        user = str(s["kiosk_user"])
        try:
            uid = pwd.getpwnam(user).pw_uid
        except KeyError:
            uid = -1

        candidates: list[str] = []
        if self._detected_runtime_dir:
            candidates.append(self._detected_runtime_dir)
        if configured != "auto":
            candidates.append(configured)
        if uid >= 0:
            candidates.append(f"/run/user/{uid}")
        candidates.extend(["/run/kioskctl-user", "/run/kioskctl"])

        out: list[str] = []
        for value in candidates:
            if value and value not in out:
                out.append(value)
        return out

    @staticmethod
    def _has_wayland_socket(runtime: str) -> bool:
        try:
            return any(
                p.exists() and not p.name.endswith(".lock")
                for p in Path(runtime).glob("wayland-*")
            )
        except Exception:
            return False

    def _runtime_dir(self) -> str:
        if self._detected_runtime_dir:
            return self._detected_runtime_dir
        # A live compositor socket is stronger evidence than a preserved config
        # value. This fixes upgraded Alpine installs whose config still named
        # /run/kioskctl while Cage was actually using /run/kioskctl-user.
        for runtime in self._runtime_dirs():
            if self._has_wayland_socket(runtime):
                return runtime
        # For PipeWire/DBus, prefer an existing user runtime with a bus.
        for runtime in self._runtime_dirs():
            if (Path(runtime) / "bus").exists():
                return runtime
        for runtime in self._runtime_dirs():
            if Path(runtime).exists():
                return runtime
        return self._runtime_dirs()[0]

    def _wayland_contexts(self) -> list[tuple[str, str]]:
        configured = str(self.cfg.get("system", {}).get("wayland_display", "auto") or "auto")
        contexts: list[tuple[str, str]] = []
        for runtime in self._runtime_dirs():
            names: list[str] = []
            if configured != "auto":
                names.append(configured)
            try:
                sockets = [p for p in Path(runtime).glob("wayland-*") if not p.name.endswith(".lock") and p.exists()]
                sockets.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                names.extend(p.name for p in sockets)
            except Exception:
                pass
            names.extend(["wayland-0", "wayland-1"])
            for name in names:
                pair = (runtime, name)
                if name and pair not in contexts:
                    contexts.append(pair)
        return contexts

    def _wayland_candidates(self) -> list[str]:
        # Backwards-compatible helper used by tests and diagnostics.
        return list(dict.fromkeys(name for _runtime, name in self._wayland_contexts()))

    def _display_snapshot(self) -> dict[str, Any] | None:
        for runtime in self._runtime_dirs():
            path = Path(runtime) / "kioskctl-display.json"
            try:
                data = json.loads(path.read_text())
                if isinstance(data, dict) and isinstance(data.get("outputs"), list):
                    return data
            except Exception:
                continue
        return None

    def wayland_display(self) -> str:
        if self._detected_wayland_display:
            return self._detected_wayland_display
        for runtime, name in self._wayland_contexts():
            candidate = Path(runtime) / name
            try:
                if candidate.exists() and not name.endswith(".lock"):
                    self._detected_runtime_dir = runtime
                    return name
            except Exception:
                pass
        snapshot = self._display_snapshot()
        if snapshot and snapshot.get("wayland_display"):
            if snapshot.get("runtime_dir"):
                self._detected_runtime_dir = str(snapshot["runtime_dir"])
            return str(snapshot["wayland_display"])
        return self._wayland_contexts()[0][1]

    def _user_env(self, wayland_display: str | None = None, runtime_dir: str | None = None) -> dict[str, str]:
        runtime = runtime_dir or self._runtime_dir()
        env = {
            "XDG_RUNTIME_DIR": runtime,
            "WAYLAND_DISPLAY": wayland_display or self.wayland_display(),
        }
        if (Path(runtime) / "bus").exists():
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime}/bus"
        return env

    def _user_env_prefix(self, wayland_display: str | None = None, runtime_dir: str | None = None) -> list[str]:
        env_args = [f"{k}={v}" for k, v in self._user_env(wayland_display, runtime_dir).items()]
        return ["runuser", "-u", str(self.cfg["system"]["kiosk_user"]), "--", "env", *env_args]

    def _run_as_kiosk(self, command: list[str], timeout: int = 10, check: bool = True, wayland_display: str | None = None, runtime_dir: str | None = None) -> subprocess.CompletedProcess[str]:
        user = str(self.cfg["system"]["kiosk_user"])
        try:
            target_uid = pwd.getpwnam(user).pw_uid
        except KeyError:
            target_uid = -1

        if os.geteuid() == target_uid:
            env = os.environ.copy()
            env.update(self._user_env(wayland_display, runtime_dir))
            return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=check, env=env)

        if shutil.which("runuser"):
            env_args = [f"{k}={v}" for k, v in self._user_env(wayland_display, runtime_dir).items()]
            full = ["runuser", "-u", user, "--", "env", *env_args, *command]
        elif shutil.which("su"):
            env_args = [f"{k}={v}" for k, v in self._user_env(wayland_display, runtime_dir).items()]
            shell_cmd = shlex.join(["env", *env_args, *command])
            full = ["su", "-s", "/bin/sh", user, "-c", shell_cmd]
        else:
            raise RuntimeError("runuser or su is required for Wayland/audio control")
        return subprocess.run(full, text=True, capture_output=True, timeout=timeout, check=check)

    def raw_wlr_randr(self) -> str:
        if not shutil.which("wlr-randr"):
            return ""
        for runtime, display in self._wayland_contexts():
            try:
                p = self._run_as_kiosk(
                    ["wlr-randr"], check=False, timeout=3,
                    wayland_display=display, runtime_dir=runtime,
                )
                if p.returncode == 0 and p.stdout.strip():
                    self._detected_runtime_dir = runtime
                    self._detected_wayland_display = display
                    return p.stdout
            except Exception:
                continue
        return ""

    @staticmethod
    def parse_outputs(text: str) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        in_modes = False
        mode_re = re.compile(r"^\s+(\d+)x(\d+)\s+px,\s*([0-9.]+)\s+Hz\s*(.*)$")
        for line in text.splitlines():
            if line and not line.startswith((" ", "\t")):
                if current:
                    outputs.append(current)
                current = {"name": line.split()[0], "description": line.strip(), "modes": [], "enabled": True}
                in_modes = False
                continue
            if not current:
                continue
            stripped = line.strip()
            if stripped.startswith("Enabled:"):
                current["enabled"] = stripped.split(":", 1)[1].strip().lower() == "yes"
            elif stripped == "Modes:":
                in_modes = True
            elif in_modes:
                m = mode_re.match(line)
                if m:
                    flags = m.group(4).lower()
                    mode = {
                        "width": int(m.group(1)),
                        "height": int(m.group(2)),
                        "refresh_hz": float(m.group(3)),
                        "preferred": "preferred" in flags,
                        "current": "current" in flags,
                    }
                    current["modes"].append(mode)
                    if mode["current"]:
                        current["current_mode"] = mode
                    if mode["preferred"]:
                        current["preferred_mode"] = mode
                    continue
                if stripped and not line.startswith(("    ", "\t\t")):
                    in_modes = False
            if stripped.startswith("Transform:"):
                current["transform"] = stripped.split(":", 1)[1].strip()
                in_modes = False
            elif stripped.startswith("Scale:"):
                try:
                    current["scale"] = float(stripped.split(":", 1)[1].strip())
                except Exception:
                    pass
                in_modes = False
            elif stripped.startswith("Position:"):
                current["position"] = stripped.split(":", 1)[1].strip()
                in_modes = False
        if current:
            outputs.append(current)
        return outputs

    def output_details(self) -> list[dict[str, Any]]:
        raw = self.raw_wlr_randr()
        if raw:
            self._display_source = "live"
            return self.parse_outputs(raw)
        snapshot = self._display_snapshot()
        if snapshot:
            outputs = snapshot.get("outputs", [])
            if isinstance(outputs, list):
                self._display_source = "session-snapshot"
                if snapshot.get("runtime_dir"):
                    self._detected_runtime_dir = str(snapshot["runtime_dir"])
                if snapshot.get("wayland_display"):
                    self._detected_wayland_display = str(snapshot["wayland_display"])
                return outputs
        self._display_source = "none"
        return []

    def display_source(self) -> str:
        return self._display_source

    def geometry_status(self, viewport: dict[str, Any] | None, output_details: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        source_details = output_details if output_details is not None else self.output_details()
        details = [x for x in source_details if x.get("enabled", True)]
        if not details or not viewport:
            return None
        configured = str(self.cfg.get("display", {}).get("output", "auto"))
        output = next((x for x in details if x.get("name") == configured), details[0])
        mode = output.get("current_mode") or output.get("preferred_mode")
        if not mode:
            return None
        scale = float(output.get("scale", 1.0) or 1.0)
        width = float(mode.get("width", 0) or 0) / scale
        height = float(mode.get("height", 0) or 0) / scale
        transform = str(output.get("transform", "normal"))
        if transform in {"90", "270", "flipped-90", "flipped-270"}:
            width, height = height, width
        browser_w = float(viewport.get("screenWidth") or viewport.get("outerWidth") or viewport.get("innerWidth") or 0)
        browser_h = float(viewport.get("screenHeight") or viewport.get("outerHeight") or viewport.get("innerHeight") or 0)
        tolerance = 4.0
        matched = abs(width - browser_w) <= tolerance and abs(height - browser_h) <= tolerance
        return {
            "output": output.get("name"),
            "expected_width": round(width, 2),
            "expected_height": round(height, 2),
            "browser_width": round(browser_w, 2),
            "browser_height": round(browser_h, 2),
            "matched": matched,
            "scale": scale,
            "transform": transform,
        }

    def outputs(self) -> list[str]:
        return [str(x["name"]) for x in self.output_details()]

    def wait_for_outputs(self, timeout: float | None = None) -> list[str]:
        timeout = float(timeout if timeout is not None else self.cfg.get("display", {}).get("settle_timeout", 12.0))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            outputs = self.outputs()
            if outputs:
                return outputs
            time.sleep(0.2)
        return []

    def _selected_outputs(self) -> list[str]:
        configured = str(self.cfg.get("display", {}).get("output", "auto"))
        return [configured] if configured != "auto" else self.outputs()

    @staticmethod
    def _mode_arg(mode: dict[str, Any]) -> str:
        refresh = float(mode.get("refresh_hz", 0) or 0)
        base = f"{int(mode['width'])}x{int(mode['height'])}"
        return f"{base}@{refresh:g}Hz" if refresh else base

    def apply_display_config(self) -> dict[str, Any]:
        details = {x["name"]: x for x in self.output_details()}
        outputs = self._selected_outputs()
        if not outputs:
            raise RuntimeError("No Wayland outputs detected")
        dcfg = self.cfg.get("display", {})
        configured_mode = str(dcfg.get("mode", "preferred"))
        configured_refresh = dcfg.get("refresh_hz", "auto")
        scale = float(dcfg.get("scale", 1.0) or 1.0)
        transform = str(dcfg.get("transform", "normal"))
        applied: list[dict[str, Any]] = []
        for output in outputs:
            command = ["wlr-randr", "--output", output, "--on"]
            selected_mode: dict[str, Any] | None = None
            info = details.get(output, {})
            if configured_mode == "preferred":
                selected_mode = info.get("preferred_mode") or info.get("current_mode")
            elif re.match(r"^\d+x\d+$", configured_mode):
                width, height = [int(x) for x in configured_mode.split("x", 1)]
                candidates = [m for m in info.get("modes", []) if m["width"] == width and m["height"] == height]
                if configured_refresh != "auto":
                    try:
                        wanted = float(configured_refresh)
                        candidates.sort(key=lambda m: abs(float(m["refresh_hz"]) - wanted))
                    except Exception:
                        pass
                selected_mode = candidates[0] if candidates else {"width": width, "height": height, "refresh_hz": 0}
            if selected_mode:
                command += ["--mode", self._mode_arg(selected_mode)]
            if scale > 0:
                command += ["--scale", f"{scale:g}"]
            if transform:
                command += ["--transform", transform]
            self._run_as_kiosk(command)
            applied.append({"output": output, "mode": selected_mode, "scale": scale, "transform": transform})
        return {"applied": applied, "outputs": self.output_details()}

    def display_power(self, on: bool, reapply: bool = True) -> None:
        outputs = self._selected_outputs()
        if not outputs:
            raise RuntimeError("No Wayland outputs detected")
        for output in outputs:
            self._run_as_kiosk(["wlr-randr", "--output", output, "--on" if on else "--off"])
        if on and reapply:
            time.sleep(0.45)
            try:
                self.apply_display_config()
            except Exception:
                pass

    def reinitialize_display(self) -> dict[str, Any]:
        outputs = self._selected_outputs()
        if not outputs:
            raise RuntimeError("No Wayland outputs detected")
        for output in outputs:
            self._run_as_kiosk(["wlr-randr", "--output", output, "--off"])
        time.sleep(0.4)
        for output in outputs:
            self._run_as_kiosk(["wlr-randr", "--output", output, "--on"])
        time.sleep(0.5)
        result = self.apply_display_config()
        time.sleep(float(self.cfg.get("display", {}).get("settle_delay", 1.0) or 0))
        return result

    def _wpctl_volume(self) -> int | None:
        if not shutil.which("wpctl"):
            return None
        # A freshly-created systemd user can need a moment for PipeWire and
        # WirePlumber to establish the default sink. Retry briefly instead of
        # reporting a permanent provider failure on the first Web UI poll.
        for attempt in range(3):
            try:
                p = self._run_as_kiosk(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=5)
                m = re.search(r"Volume:\s+([0-9.]+)", p.stdout)
                if m:
                    return round(float(m.group(1)) * 100)
            except Exception:
                pass
            if attempt < 2:
                time.sleep(0.35)
        return None

    def _pactl_volume(self) -> int | None:
        if not shutil.which("pactl"):
            return None
        try:
            p = self._run_as_kiosk(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
            m = re.search(r"(\d+)%", p.stdout)
            return int(m.group(1)) if m else None
        except Exception:
            return None

    def _alsa_control(self) -> str | None:
        if not shutil.which("amixer"):
            return None
        try:
            p = self._run_as_kiosk(["amixer", "scontrols"])
            names = re.findall(r"Simple mixer control '([^']+)'", p.stdout)
            for preferred in ("Master", "PCM", "Speaker", "Headphone"):
                if preferred in names:
                    return preferred
            return names[0] if names else None
        except Exception:
            return None

    def _alsa_volume(self) -> int | None:
        control = self._alsa_control()
        if not control:
            return None
        try:
            p = self._run_as_kiosk(["amixer", "sget", control])
            vals = [int(x) for x in re.findall(r"\[(\d+)%\]", p.stdout)]
            return round(sum(vals) / len(vals)) if vals else None
        except Exception:
            return None

    def audio_status(self) -> dict[str, Any]:
        requested = str(self.cfg.get("audio", {}).get("provider", "auto"))
        probes = []
        if requested in ("auto", "pipewire"):
            probes.append(("pipewire", self._wpctl_volume))
        if requested in ("auto", "pulseaudio"):
            probes.append(("pulseaudio", self._pactl_volume))
        if requested in ("auto", "alsa"):
            probes.append(("alsa", self._alsa_volume))
        for provider, func in probes:
            value = func()
            if value is not None:
                return {"provider": provider, "volume": value, "available": True}
        return {"provider": None, "volume": None, "available": False}

    def get_volume(self) -> int | None:
        return self.audio_status()["volume"]

    def set_volume(self, percent: int) -> str:
        percent = max(0, min(100, int(percent)))
        status = self.audio_status()
        provider = status.get("provider")
        if provider == "pipewire":
            self._run_as_kiosk(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%"])
        elif provider == "pulseaudio":
            self._run_as_kiosk(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"])
        elif provider == "alsa":
            control = self._alsa_control()
            if not control:
                raise RuntimeError("ALSA is installed but no mixer control was found")
            self._run_as_kiosk(["amixer", "sset", control, f"{percent}%"])
        else:
            raise RuntimeError("No supported audio provider is available (PipeWire/PulseAudio/ALSA)")
        return str(provider)

    def get_brightness(self) -> int | None:
        if not shutil.which("brightnessctl"):
            return None
        try:
            p = subprocess.run(["brightnessctl", "-m"], text=True, capture_output=True, timeout=5, check=True)
            m = re.search(r",(\d+)%", p.stdout)
            return int(m.group(1)) if m else None
        except Exception:
            return None

    def set_brightness(self, percent: int) -> None:
        if not shutil.which("brightnessctl"):
            raise RuntimeError("brightnessctl is not installed or no backlight device is available")
        percent = max(1, min(100, int(percent)))
        subprocess.run(["brightnessctl", "set", f"{percent}%"], check=True, timeout=10)


def power_action(action: str, allowed: bool) -> None:
    if not allowed:
        raise PermissionError("Power actions are disabled in configuration")
    if action not in {"reboot", "shutdown"}:
        raise ValueError("Unknown power action")
    if shutil.which("systemctl") and Path("/run/systemd/system").exists():
        command = ["systemctl", "reboot" if action == "reboot" else "poweroff"]
    else:
        binary = "reboot" if action == "reboot" else "poweroff"
        resolved = shutil.which(binary)
        if not resolved:
            raise RuntimeError(f"No supported {action} command found")
        command = [resolved]
    subprocess.Popen(command)
