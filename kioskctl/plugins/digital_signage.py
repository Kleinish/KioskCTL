from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .manifest import PluginManifest

_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}


class DigitalSignagePlugin:
    id = 'digital_signage'
    name = 'Digital Signage'
    provides_screensaver = True
    manifest = PluginManifest(
        id=id,
        name=name,
        version='1.0',
        description='Scheduled local-image signage for ads, announcements and rotating company content.',
        capabilities=('screensaver.provider', 'signage.local-assets', 'signage.schedule'),
        permissions=('browser.navigate', 'filesystem.plugin-data', 'status.read'),
        config_schema=(
            {'key': 'enabled', 'type': 'boolean', 'label': 'Enable digital signage', 'default': False},
            {'key': 'after_seconds', 'type': 'integer', 'label': 'Start after (seconds)', 'default': 120},
            {'key': 'interval_seconds', 'type': 'integer', 'label': 'Slide interval (seconds)', 'default': 10},
            {'key': 'fit', 'type': 'select', 'label': 'Image fit', 'options': ['contain', 'cover'], 'default': 'cover'},
            {'key': 'shuffle', 'type': 'boolean', 'label': 'Shuffle images', 'default': False},
            {'key': 'background', 'type': 'color', 'label': 'Background', 'default': '#000000'},
            {'key': 'keep_display_on', 'type': 'boolean', 'label': 'Keep display on', 'default': True},
            {'key': 'schedule_enabled', 'type': 'boolean', 'label': 'Use schedule', 'default': False},
            {'key': 'schedule_start', 'type': 'time', 'label': 'Start time', 'default': '00:00'},
            {'key': 'schedule_end', 'type': 'time', 'label': 'End time', 'default': '23:59'},
        ),
    )

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.started = False
        self.last_error: str | None = None

    def config(self) -> dict[str, Any]:
        return self.cfg.setdefault('plugins', {}).setdefault('digital_signage', {})

    @property
    def installed(self) -> bool:
        return bool(self.config().get('installed', False))

    @property
    def enabled(self) -> bool:
        return self.installed and bool(self.config().get('enabled', False))

    @property
    def after_seconds(self) -> int:
        return max(1, int(self.config().get('after_seconds', 120) or 120))

    @property
    def keep_display_on(self) -> bool:
        return bool(self.config().get('keep_display_on', True))

    def start(self) -> None:
        self.started = True
        if self.installed:
            self.asset_dir().mkdir(parents=True, exist_ok=True)

    def stop(self) -> None:
        self.started = False

    def asset_dir(self) -> Path:
        raw = str(self.config().get('asset_dir', '/var/lib/kioskctl/plugins/digital-signage/assets'))
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def safe_name(name: str) -> str:
        base = os.path.basename(str(name or '').strip())
        if not base or base in {'.', '..'} or Path(base).suffix.lower() not in _IMAGE_EXTS:
            raise ValueError('signage image must be PNG, JPG, JPEG, WEBP, or GIF')
        return base[:180]

    def assets(self) -> list[str]:
        root = self.asset_dir()
        return sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS)

    def schedule_active(self, now: datetime | None = None) -> bool:
        c = self.config()
        if not bool(c.get('schedule_enabled', False)):
            return True
        now = now or datetime.now()
        days = c.get('schedule_days', [0, 1, 2, 3, 4, 5, 6])
        try:
            allowed = {int(x) for x in days}
        except Exception:
            allowed = set(range(7))
        if now.weekday() not in allowed:
            return False
        def mins(value: str, default: int) -> int:
            try:
                h, m = str(value).split(':', 1)
                return max(0, min(1439, int(h) * 60 + int(m)))
            except Exception:
                return default
        start = mins(str(c.get('schedule_start', '00:00')), 0)
        end = mins(str(c.get('schedule_end', '23:59')), 1439)
        current = now.hour * 60 + now.minute
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    def available_now(self) -> bool:
        return self.enabled and self.schedule_active() and bool(self.assets())

    def screen_url(self, admin_port: int) -> str:
        return f'http://127.0.0.1:{admin_port}/plugin/digital-signage/screen'

    def status(self) -> dict[str, Any]:
        c = self.config()
        return {
            'id': self.id,
            'name': self.name,
            'installed': self.installed,
            'enabled': self.enabled,
            'started': self.started,
            'asset_count': len(self.assets()) if self.installed else 0,
            'images': self.assets() if self.installed else [],
            'schedule_active': self.schedule_active() if self.installed else False,
            'after_seconds': int(c.get('after_seconds', 120) or 120),
            'interval_seconds': int(c.get('interval_seconds', 10) or 10),
            'fit': str(c.get('fit', 'cover')),
            'shuffle': bool(c.get('shuffle', False)),
            'background': str(c.get('background', '#000000')),
            'keep_display_on': bool(c.get('keep_display_on', True)),
            'schedule_enabled': bool(c.get('schedule_enabled', False)),
            'schedule_start': str(c.get('schedule_start', '00:00')),
            'schedule_end': str(c.get('schedule_end', '23:59')),
            'schedule_days': list(c.get('schedule_days', [0, 1, 2, 3, 4, 5, 6])),
            'last_error': self.last_error,
        }
