from __future__ import annotations

import os

from .browser import build_browser_command
from .config import load_config


def main() -> None:
    # V0.3.1 deliberately launches Chromium immediately, matching the proven
    # V0.2 session path. Display configuration is applied by a separate helper
    # so Cage always has a real Wayland client right away.
    cfg = load_config()
    cmd = ["cage", "-d", "--", *build_browser_command(cfg)]
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
