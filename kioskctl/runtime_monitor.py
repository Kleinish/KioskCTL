from __future__ import annotations

import sys
import time
from typing import Any

from .browser import DevTools, browser_runtime_config
from .config import load_config


def _expected(features: dict[str, Any]) -> dict[str, bool]:
    return {
        "pull": bool(features.get("pull_to_refresh")),
        "edge": bool(features.get("edge_drawer")),
        "keyboard": bool(features.get("onscreen_keyboard")),
    }


def _missing(state: dict[str, Any], features: dict[str, Any]) -> list[str]:
    expected = _expected(features)
    return [name for name, wanted in expected.items() if wanted and not bool(state.get(name))]


def main() -> None:
    """Keep browser-side kiosk helpers attached across redirects/navigation.

    Home Assistant's OAuth flow can navigate or replace the DevTools page target
    during startup. A one-shot injection races that transition and may install
    helpers into a document that disappears milliseconds later. This session
    monitor deliberately stays alive beside Cage, observes the current external
    page target, and (re)installs the runtime whenever the target changes or the
    expected helpers are missing.
    """
    last_target_id: str | None = None
    last_url: str | None = None
    last_ok: tuple[bool, bool, bool] | None = None
    last_warning: str | None = None
    last_color_scheme: str | None = None

    while True:
        try:
            cfg = load_config()
            bcfg = cfg.get("browser", {})
            dt = DevTools(int(bcfg.get("devtools_port", 9222)), str(bcfg.get("url", "")))
            if not dt.available():
                time.sleep(0.75)
                continue

            target = dt.target_info()
            target_id = str(target.get("id") or "")
            url = str(target.get("url") or "")
            features = browser_runtime_config(cfg)
            color_scheme = str(bcfg.get("color_scheme", "auto") or "auto").lower()

            # Local idle-content surfaces are purpose-built full-screen pages
            # and deliberately do not host pull/edge/keyboard helpers. Treat
            # core Simple screensaver and plugin screensaver routes as valid
            # terminal runtime states instead of repeatedly attempting runtime
            # injection while signage is active.
            local_idle_surface = (
                "/screensaver" in url
                or "/plugin/digital-signage/" in url
                or "/plugin/immich/" in url
            )
            if (url.startswith("http://127.0.0.1:") or url.startswith("http://localhost:")) and local_idle_surface:
                last_target_id = target_id or last_target_id
                last_url = url or last_url
                last_ok = (False, False, False)
                last_warning = None
                time.sleep(1.5)
                continue

            try:
                state = dt.runtime_feature_state()
            except Exception:
                state = {}

            missing = _missing(state, features)
            target_changed = bool(target_id and target_id != last_target_id)
            runtime_missing = not bool(state.get("runtime")) or bool(missing)

            if target_changed or color_scheme != last_color_scheme:
                dt.set_color_scheme(color_scheme)
                if color_scheme != last_color_scheme:
                    print(f"kioskctl-browser: page color scheme: {color_scheme}", flush=True)
                last_color_scheme = color_scheme

            if target_changed or runtime_missing:
                try:
                    result = dt.install_runtime_features(cfg)
                    runtime = result.get("runtime", {})
                    flags = (
                        bool(runtime.get("pull")),
                        bool(runtime.get("edge")),
                        bool(runtime.get("keyboard")),
                    )
                    if target_changed or flags != last_ok or url != last_url:
                        print(
                            "kioskctl-browser: runtime features active: "
                            f"pull={flags[0]} edge={flags[1]} keyboard={flags[2]} "
                            f"target={runtime.get('url') or url or 'unknown'}",
                            flush=True,
                        )
                    last_ok = flags
                    last_warning = None
                except Exception as exc:
                    message = str(exc)
                    if message != last_warning:
                        print(
                            f"kioskctl-browser: runtime feature injection waiting/retrying: {message}",
                            file=sys.stderr,
                            flush=True,
                        )
                        last_warning = message
                    # OAuth/callback pages can disappear while CDP is operating.
                    # Treat that as transient and retry the new target shortly.
                    time.sleep(0.6)
                    continue

            last_target_id = target_id or last_target_id
            last_url = url or last_url
        except Exception as exc:
            message = str(exc)
            if message != last_warning:
                print(f"kioskctl-browser: runtime monitor warning: {message}", file=sys.stderr, flush=True)
                last_warning = message

        time.sleep(1.5)


if __name__ == "__main__":
    main()
