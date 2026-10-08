from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger('kioskctl.plugins')


class PluginManager:
    def __init__(self) -> None:
        self._plugins: dict[str, Any] = {}

    def register(self, plugin: Any) -> None:
        if plugin.id in self._plugins:
            raise ValueError(f'Duplicate plugin id: {plugin.id}')
        self._plugins[plugin.id] = plugin

    def get(self, plugin_id: str) -> Any | None:
        return self._plugins.get(plugin_id)

    def start(self) -> None:
        for plugin in self._plugins.values():
            try:
                plugin.start()
            except Exception:
                logger.exception('Plugin %s failed to start', plugin.id)

    def stop(self) -> None:
        for plugin in reversed(list(self._plugins.values())):
            try:
                plugin.stop()
            except Exception:
                logger.exception('Plugin %s failed to stop', plugin.id)

    def manifests(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for plugin_id, plugin in self._plugins.items():
            manifest = getattr(plugin, 'manifest', None)
            if manifest is not None and hasattr(manifest, 'as_dict'):
                result[plugin_id] = manifest.as_dict()
            else:
                result[plugin_id] = {'id': plugin_id, 'name': getattr(plugin, 'name', plugin_id), 'built_in': True}
        return result

    def status(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for plugin_id, plugin in self._plugins.items():
            try:
                current = plugin.status()
                manifest = getattr(plugin, 'manifest', None)
                if manifest is not None and hasattr(manifest, 'as_dict'):
                    current = {**current, 'manifest': manifest.as_dict()}
                result[plugin_id] = current
            except Exception as exc:
                result[plugin_id] = {'id': plugin_id, 'name': getattr(plugin, 'name', plugin_id), 'error': str(exc)}
        return result

    def catalog(self) -> list[dict[str, Any]]:
        """Return Web-UI-friendly catalog metadata for bundled plugins.

        v0.5 starts with official bundled plugins. The catalog/install API is
        intentionally the same shape we can later back with signed external
        packages without changing the Web UI.
        """
        statuses = self.status()
        out: list[dict[str, Any]] = []
        for plugin_id, plugin in self._plugins.items():
            manifest = getattr(plugin, 'manifest', None)
            data = manifest.as_dict() if manifest is not None and hasattr(manifest, 'as_dict') else {
                'id': plugin_id,
                'name': getattr(plugin, 'name', plugin_id),
                'description': '',
                'version': '1.0',
                'built_in': True,
            }
            current = statuses.get(plugin_id, {})
            data['installed'] = bool(current.get('installed', True))
            data['enabled'] = bool(current.get('enabled', False))
            data['status'] = current
            out.append(data)
        return out

    def screensaver_provider(self) -> Any | None:
        """Return the first installed/enabled plugin that owns idle content.

        Only one provider is expected to be enabled at a time. API handlers
        enforce that for bundled providers; this deterministic fallback keeps
        startup safe if a hand-edited config enables more than one.
        """
        for plugin in self._plugins.values():
            if not bool(getattr(plugin, 'provides_screensaver', False)):
                continue
            if bool(getattr(plugin, 'enabled', False)):
                return plugin
        return None
