from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger("kioskctl.events")
EventCallback = Callable[[str, dict[str, Any]], None]


class EventBus:
    """Small in-process event bus used by optional integrations/plugins."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, list[EventCallback]] = defaultdict(list)

    def subscribe(self, event: str, callback: EventCallback) -> None:
        with self._lock:
            if callback not in self._subscribers[event]:
                self._subscribers[event].append(callback)

    def unsubscribe(self, event: str, callback: EventCallback) -> None:
        with self._lock:
            callbacks = self._subscribers.get(event, [])
            if callback in callbacks:
                callbacks.remove(callback)

    def emit(self, event: str, **payload: Any) -> None:
        with self._lock:
            callbacks = list(self._subscribers.get(event, [])) + list(self._subscribers.get("*", []))
        for callback in callbacks:
            try:
                callback(event, payload)
            except Exception:
                logger.exception("Event subscriber failed for %s", event)
