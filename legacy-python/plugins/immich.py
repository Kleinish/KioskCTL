from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .manifest import PluginManifest

logger = logging.getLogger('kioskctl.plugins.immich')


class ImmichPlugin:
    id = 'immich'
    name = 'Immich Screensaver'
    provides_screensaver = True
    manifest = PluginManifest(
        id=id,
        name=name,
        version='1.0',
        description='Use photos from an Immich server as idle-screen content.',
        capabilities=('screensaver.provider', 'immich.random', 'immich.album'),
        permissions=('network.http', 'browser.navigate', 'status.read', 'secret.store'),
        config_schema=(
            {'key': 'enabled', 'type': 'boolean', 'label': 'Enable Immich screensaver', 'default': False},
            {'key': 'server_url', 'type': 'string', 'label': 'Immich server URL', 'default': ''},
            {'key': 'api_key', 'type': 'secret', 'label': 'API key', 'default': ''},
            {'key': 'album_id', 'type': 'string', 'label': 'Album ID (optional)', 'default': ''},
            {'key': 'after_seconds', 'type': 'integer', 'label': 'Start after (seconds)', 'default': 120},
            {'key': 'interval_seconds', 'type': 'integer', 'label': 'Slide interval (seconds)', 'default': 15},
            {'key': 'fit', 'type': 'select', 'label': 'Image fit', 'options': ['contain', 'cover'], 'default': 'contain'},
            {'key': 'background', 'type': 'color', 'label': 'Background', 'default': '#000000'},
            {'key': 'keep_display_on', 'type': 'boolean', 'label': 'Keep display on', 'default': True},
        ),
    )

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.started = False
        self.last_error: str | None = None
        self.last_refresh: float | None = None
        self._assets: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def config(self) -> dict[str, Any]:
        return self.cfg.setdefault('plugins', {}).setdefault('immich', {})

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

    def stop(self) -> None:
        self.started = False

    def _base(self) -> str:
        return str(self.config().get('server_url', '') or '').strip().rstrip('/')

    def _headers(self) -> dict[str, str]:
        key = str(self.config().get('api_key', '') or '')
        return {'Accept': 'application/json', 'x-api-key': key}

    def _request_json(self, path: str, *, method: str = 'GET', body: dict[str, Any] | None = None, timeout: float = 8.0) -> Any:
        base = self._base()
        if not base.startswith(('http://', 'https://')):
            raise RuntimeError('Immich server URL must begin with http:// or https://')
        headers = self._headers()
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(512).decode('utf-8', 'replace')
            except Exception:
                detail = ''
            raise RuntimeError(f'Immich HTTP {exc.code}: {detail or exc.reason}') from exc
        except Exception as exc:
            raise RuntimeError(f'Immich request failed: {exc}') from exc

    @staticmethod
    def _asset_list(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = payload.get('assets') or payload.get('items') or payload.get('results') or []
        else:
            items = []
        out: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or not item.get('id'):
                continue
            asset_type = str(item.get('type', 'IMAGE') or 'IMAGE').upper()
            if asset_type not in {'IMAGE', 'PHOTO'}:
                continue
            out.append({
                'id': str(item['id']),
                'file_name': str(item.get('originalFileName') or item.get('fileName') or item['id']),
                'original_mime_type': str(item.get('originalMimeType') or item.get('mimeType') or ''),
                'width': item.get('width'),
                'height': item.get('height'),
            })
        return out

    def refresh_assets(self, *, force: bool = False) -> list[dict[str, Any]]:
        c = self.config()
        cache_seconds = max(30, int(c.get('cache_seconds', 300) or 300))
        with self._lock:
            if not force and self._assets and self.last_refresh and (time.monotonic() - self.last_refresh) < cache_seconds:
                return list(self._assets)
        album_id = str(c.get('album_id', '') or '').strip()
        try:
            if album_id:
                payload = self._request_json('/api/albums/' + urllib.parse.quote(album_id, safe=''))
            else:
                count = max(1, min(500, int(c.get('random_count', 100) or 100)))
                payload = self._request_json('/api/search/random', method='POST', body={'type': 'IMAGE', 'size': count})
            assets = self._asset_list(payload)
            if not assets:
                raise RuntimeError('Immich returned no image assets')
            with self._lock:
                self._assets = assets
                self.last_refresh = time.monotonic()
                self.last_error = None
            return list(assets)
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning('Immich asset refresh failed: %s', exc)
            with self._lock:
                if self._assets:
                    return list(self._assets)
            raise

    def available_now(self) -> bool:
        if not self.enabled or not self._base() or not str(self.config().get('api_key', '') or ''):
            return False
        try:
            return bool(self.refresh_assets())
        except Exception:
            return False

    def screen_url(self, admin_port: int) -> str:
        return f'http://127.0.0.1:{admin_port}/plugin/immich/screen'

    _BROWSER_IMAGE_TYPES = {
        'image/apng',
        'image/avif',
        'image/bmp',
        'image/gif',
        'image/jpeg',
        'image/jpg',
        'image/png',
        'image/webp',
    }

    def _cached_asset(self, asset_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._assets:
                if str(item.get('id')) == str(asset_id):
                    return dict(item)
        return None

    def _asset_details(self, asset_id: str) -> dict[str, Any]:
        cached = self._cached_asset(asset_id)
        if cached and cached.get('original_mime_type'):
            return cached
        payload = self._request_json('/api/assets/' + urllib.parse.quote(str(asset_id), safe=''))
        if not isinstance(payload, dict):
            return cached or {'id': str(asset_id)}
        return {
            'id': str(payload.get('id') or asset_id),
            'file_name': str(payload.get('originalFileName') or payload.get('fileName') or asset_id),
            'original_mime_type': str(payload.get('originalMimeType') or payload.get('mimeType') or ''),
            'width': payload.get('width'),
            'height': payload.get('height'),
        }

    def proxy_image(self, asset_id: str) -> tuple[bytes, str]:
        """Fetch an Immich asset without allowing a derivative to define framing.

        Browser-native originals (JPEG/PNG/WebP/AVIF/GIF/etc.) are fetched from
        Immich's ``/original`` endpoint.  This guarantees that Contain receives
        the uncropped source pixels.  Formats Chromium cannot reliably display
        (HEIC/HEIF/RAW and similar) fall back to Immich's browser-compatible
        ``fullsize`` representation.

        Both paths are proxied through kioskctl so the API key remains local to
        the kiosk.  ``asset.download`` permission is required for originals.
        """
        base = self._base()
        if not base:
            raise RuntimeError('Immich server URL is not configured')

        details = self._asset_details(asset_id)
        original_mime = str(details.get('original_mime_type') or '').split(';', 1)[0].strip().lower()
        quoted = urllib.parse.quote(str(asset_id), safe='')
        use_original = original_mime in self._BROWSER_IMAGE_TYPES
        if use_original:
            url = f'{base}/api/assets/{quoted}/original'
            source_name = 'original'
        else:
            url = f'{base}/api/assets/{quoted}/thumbnail?size=fullsize'
            source_name = 'fullsize-fallback'

        req = urllib.request.Request(
            url,
            headers={**self._headers(), 'Accept': 'image/*'},
            method='GET',
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read(100 * 1024 * 1024 + 1)
                if len(raw) > 100 * 1024 * 1024:
                    raise RuntimeError(f'Immich {source_name} image exceeded 100 MiB')
                content_type = str(response.headers.get_content_type() or original_mime or 'image/jpeg')
                return raw, content_type
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise RuntimeError(
                    f'Immich denied the {source_name} image request. Ensure this API key has '
                    'asset view and asset download permissions.'
                ) from exc
            raise RuntimeError(f'Unable to fetch Immich {source_name} image: HTTP {exc.code} {exc.reason}') from exc
        except Exception as exc:
            raise RuntimeError(f'Unable to fetch Immich {source_name} image: {exc}') from exc

    def test_connection(self) -> dict[str, Any]:
        """Validate both Immich metadata access and slideshow image access.

        Browser-native assets use the original download endpoint while formats
        such as HEIC/RAW use Immich's fullsize browser-compatible derivative.
        Testing one actual slideshow image proves the configured API key can
        access the exact source path used during playback.
        """
        payload = self._request_json('/api/server/about')
        assets = self.refresh_assets(force=True)
        if not assets:
            raise RuntimeError('Immich returned no image assets')

        # Fetch one image through the exact path used by slideshow playback so
        # API permissions, redirects and full-size rendering are all proven.
        sample_id = str(assets[0]['id'])
        sample_bytes, sample_type = self.proxy_image(sample_id)
        if not sample_bytes:
            raise RuntimeError('Immich returned an empty full-size image')

        version = None
        if isinstance(payload, dict):
            version = payload.get('version') or payload.get('versionName')
        return {
            'ok': True,
            'server_version': version,
            'asset_count': len(assets),
            'image_source': 'original-or-fullsize',
            'sample_content_type': sample_type,
            'sample_bytes': len(sample_bytes),
        }

    def status(self) -> dict[str, Any]:
        c = self.config()
        with self._lock:
            count = len(self._assets)
        return {
            'id': self.id,
            'name': self.name,
            'installed': self.installed,
            'enabled': self.enabled,
            'started': self.started,
            'server_url': self._base(),
            'api_key_set': bool(str(c.get('api_key', '') or '')),
            'album_id': str(c.get('album_id', '') or ''),
            'after_seconds': int(c.get('after_seconds', 120) or 120),
            'interval_seconds': int(c.get('interval_seconds', 15) or 15),
            'fit': str(c.get('fit', 'contain')),
            'background': str(c.get('background', '#000000')),
            'keep_display_on': bool(c.get('keep_display_on', True)),
            'random_count': int(c.get('random_count', 100) or 100),
            'asset_count': count,
            'image_source': 'original-or-fullsize',
            'last_error': self.last_error,
        }
