from __future__ import annotations

from typing import Any, Protocol

from .manifest import PluginManifest


class Plugin(Protocol):
    id: str
    name: str
    manifest: PluginManifest

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def status(self) -> dict[str, Any]: ...
