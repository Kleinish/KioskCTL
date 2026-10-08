from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    description: str
    capabilities: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    config_schema: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    built_in: bool = True

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities"] = list(self.capabilities)
        data["permissions"] = list(self.permissions)
        data["config_schema"] = list(self.config_schema)
        return data
