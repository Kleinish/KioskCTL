from __future__ import annotations

import os
import sys
import time

from .browser import build_browser_command
from .config import load_config
from .platform import WaylandTools


def main() -> None:
    cfg = load_config()
    tools = WaylandTools(cfg)
    outputs = tools.wait_for_outputs()
    if outputs:
        print(f"kioskctl: Wayland outputs ready: {', '.join(outputs)}", flush=True)
        if cfg.get("display", {}).get("reinitialize_on_start", True):
            try:
                result = tools.apply_display_config()
                print(f"kioskctl: display configuration applied: {result['applied']}", flush=True)
            except Exception as exc:
                print(f"kioskctl: warning: display configuration failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(float(cfg.get("display", {}).get("settle_delay", 1.0) or 0))
    else:
        print("kioskctl: warning: no Wayland output became ready before timeout; starting browser anyway", file=sys.stderr, flush=True)

    cmd = build_browser_command(cfg)
    print(f"kioskctl: starting browser provider: {cmd[0]}", flush=True)
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
