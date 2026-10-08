from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from .browser import DevTools
from .config import load_config
from .platform import WaylandTools


def _write_display_snapshot(tools: WaylandTools) -> None:
    """Publish display state from inside the real graphical session.

    The management agent intentionally runs outside the compositor session.
    A small runtime snapshot gives it a reliable read-only fallback when
    runuser/su probing is restricted or when an upgraded distro retained a
    stale runtime-dir setting.
    """
    try:
        details = tools.output_details()
        runtime = Path(tools._runtime_dir())
        runtime.mkdir(parents=True, exist_ok=True)
        target = runtime / "kioskctl-display.json"
        tmp = runtime / f".kioskctl-display.{os.getpid()}.tmp"
        payload = {
            "version": 1,
            "runtime_dir": str(runtime),
            "wayland_display": tools.wayland_display(),
            "outputs": details,
            "updated_at": time.time(),
        }
        tmp.write_text(json.dumps(payload, separators=(",", ":")))
        tmp.chmod(0o600)
        tmp.replace(target)
        print(f"kioskctl-display: state published: {target}", flush=True)
    except Exception as exc:
        print(f"kioskctl-display: warning: could not publish display state: {exc}", file=sys.stderr, flush=True)




def _display_needs_post_start_reinitialize(cfg: dict) -> bool:
    dcfg = cfg.get("display", {})
    transform = str(dcfg.get("transform", "normal"))
    scale = float(dcfg.get("scale", 1.0) or 1.0)
    mode = str(dcfg.get("mode", "preferred"))
    refresh = str(dcfg.get("refresh_hz", "auto"))
    # A second modeset after Chromium maps fixes wlroots/Cage combinations
    # (notably Arch and Debian in the laptop matrix) that accept the initial
    # transform but do not commit it until the output is reprobed. It also
    # makes Browser > Restart preserve non-default display settings.
    return transform != "normal" or abs(scale - 1.0) > 0.001 or mode != "preferred" or refresh != "auto"

def main() -> None:
    cfg = load_config()
    tools = WaylandTools(cfg)
    outputs = tools.wait_for_outputs()
    if not outputs:
        print("kioskctl-display: no Wayland output became ready before timeout", file=sys.stderr, flush=True)
        return

    print(f"kioskctl-display: outputs ready: {', '.join(outputs)}", flush=True)
    if cfg.get("display", {}).get("reinitialize_on_start", True):
        try:
            result = tools.apply_display_config()
            print(f"kioskctl-display: configuration applied: {result['applied']}", flush=True)
        except Exception as exc:
            print(f"kioskctl-display: configuration failed: {exc}", file=sys.stderr, flush=True)

    _write_display_snapshot(tools)
    time.sleep(float(cfg.get("display", {}).get("settle_delay", 1.0) or 0))

    # If Chromium is already up, notify it about the new geometry. If it is
    # still starting, wait briefly. This replaces the V0.2 manual screen
    # off/on workaround seen on Arch.
    dt = DevTools(int(cfg["browser"].get("devtools_port", 9222)), str(cfg["browser"].get("url", "")))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if dt.available():
                # Browser-side touch helpers are maintained by the long-lived
                # runtime_monitor process. Keep display setup independent so an
                # OAuth navigation race cannot make display_fixup give up on
                # runtime features permanently.
                if cfg.get("display", {}).get("reinitialize_on_start", True) and _display_needs_post_start_reinitialize(cfg):
                    try:
                        result = tools.reinitialize_display()
                        print(f"kioskctl-display: post-browser reinitialize applied: {result['applied']}", flush=True)
                        _write_display_snapshot(tools)
                    except Exception as exc:
                        print(f"kioskctl-display: warning: post-browser display reinitialize failed: {exc}", file=sys.stderr, flush=True)
                dt.notify_geometry_change()
                print("kioskctl-display: browser geometry refreshed", flush=True)
                return
        except Exception:
            pass
        time.sleep(0.4)

    print(
        "kioskctl-display: warning: browser DevTools did not become ready within 15 seconds; "
        "geometry refresh was skipped",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    main()
