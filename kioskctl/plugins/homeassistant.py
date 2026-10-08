from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from ..events import EventBus
from ..mqtt import MQTTBridge
from .manifest import PluginManifest

logger = logging.getLogger("kioskctl.plugins.homeassistant")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HomeAssistantPlugin:
    id = "homeassistant"
    name = "Home Assistant"
    manifest = PluginManifest(
        id="homeassistant",
        name="Home Assistant",
        version="1.0",
        description="Home Assistant MQTT discovery and entity control.",
        capabilities=("homeassistant.discovery", "homeassistant.birth-republish", "mqtt.entities"),
        permissions=("mqtt.publish", "mqtt.subscribe", "status.read"),
        config_schema=(
            {"key": "enabled", "type": "boolean", "label": "Enable Home Assistant plugin", "default": False},
            {"key": "discovery_prefix", "type": "string", "label": "Discovery prefix", "default": "homeassistant"},
        ),
    )

    def __init__(
        self,
        cfg: dict[str, Any],
        mqtt: MQTTBridge,
        event_bus: EventBus,
        get_status: Callable[[], dict[str, Any]],
        version: str,
    ) -> None:
        self.cfg = cfg
        self.mqtt = mqtt
        self.event_bus = event_bus
        self.get_status = get_status
        self.version = version
        self.started = False
        self.last_publish: str | None = None
        self.last_error: str | None = None
        self.publish_count = 0
        self.entity_count = 0
        self._registered = False

    def config(self) -> dict[str, Any]:
        return self.cfg.setdefault("plugins", {}).setdefault(
            "homeassistant", {"enabled": False, "discovery_prefix": "homeassistant"}
        )

    @property
    def enabled(self) -> bool:
        return bool(self.config().get("enabled", False))

    @property
    def prefix(self) -> str:
        return str(self.config().get("discovery_prefix", "homeassistant") or "homeassistant")

    def start(self) -> None:
        self.started = True
        if not self._registered:
            self.mqtt.add_connect_listener(self._on_mqtt_connected)
            self.mqtt.subscribe("homeassistant/status", self._on_homeassistant_status)
            self.event_bus.subscribe("browser.experience_changed", self._on_experience_changed)
            self._registered = True
        if self.enabled and self.mqtt.connected:
            self.publish_discovery()

    def stop(self) -> None:
        self.started = False

    def _on_mqtt_connected(self, bridge: MQTTBridge) -> None:
        if self.enabled:
            self.publish_discovery()

    def _on_homeassistant_status(self, topic: str, payload: str) -> None:
        if self.enabled and payload.strip().lower() == "online":
            logger.info("Home Assistant: birth message received; republishing discovery")
            self.publish_discovery()

    def _on_experience_changed(self, event: str, payload: dict[str, Any]) -> None:
        # Page names are select options in Home Assistant, so republish when the
        # browser experience configuration changes.
        if payload.get("pages_changed") and self.enabled and self.mqtt.connected:
            self.publish_discovery()

    def _device(self) -> dict[str, Any]:
        return {
            "identifiers": [f"kioskctl_{self.mqtt.device_id}"],
            "name": str(self.cfg["device"]["name"]),
            "manufacturer": "kioskctl",
            "model": "Linux Kiosk",
            "sw_version": self.version,
        }

    def _origin(self) -> dict[str, Any]:
        return {"name": "kioskctl", "sw_version": self.version}

    def _entities(self) -> dict[str, tuple[str, dict[str, Any]]]:
        base = self.mqtt.base
        state = f"{base}/state"
        command = f"{base}/command"
        return {
            # Preserve the three 0.3.x unique IDs/topics so existing HA devices
            # update in place when the integration moves into this plugin.
            "status": ("sensor", {
                "name": "Status",
                "state_topic": f"{base}/availability",
                "icon": "mdi:lan-connect",
            }),
            "reboot": ("button", {
                "name": "Reboot",
                "command_topic": f"{command}/reboot",
                "payload_press": "PRESS",
                "device_class": "restart",
                "entity_category": "config",
            }),
            "reload": ("button", {
                "name": "Reload Browser",
                "command_topic": f"{command}/reload",
                "payload_press": "PRESS",
            }),
            "browser": ("binary_sensor", {
                "name": "Browser",
                "state_topic": state,
                "value_template": "{{ 'ON' if value_json.browser_active else 'OFF' }}",
                "payload_on": "ON",
                "payload_off": "OFF",
                "device_class": "connectivity",
            }),
            "current_url": ("sensor", {
                "name": "Current URL",
                "state_topic": state,
                "value_template": "{{ value_json.current_url if value_json.current_url else value_json.configured_url }}",
                "icon": "mdi:web",
            }),
            "screen": ("switch", {
                "name": "Screen",
                "command_topic": f"{command}/screen",
                "payload_on": "ON",
                "payload_off": "OFF",
                "optimistic": True,
                "icon": "mdi:monitor",
            }),
            "brightness": ("number", {
                "name": "Brightness",
                "command_topic": f"{command}/brightness",
                "state_topic": state,
                "value_template": "{{ value_json.brightness }}",
                "min": 1,
                "max": 100,
                "step": 1,
                "mode": "slider",
                "unit_of_measurement": "%",
            }),
            "volume": ("number", {
                "name": "Volume",
                "command_topic": f"{command}/volume",
                "state_topic": state,
                "value_template": "{{ value_json.volume }}",
                "min": 0,
                "max": 100,
                "step": 1,
                "mode": "slider",
                "unit_of_measurement": "%",
            }),
            "rotation": ("select", {
                "name": "Rotation",
                "command_topic": f"{command}/rotation",
                "state_topic": state,
                "value_template": "{{ value_json.display_config.transform }}",
                "options": ["normal", "90", "180", "270"],
                "entity_category": "config",
            }),
            "url": ("text", {
                "name": "URL",
                "command_topic": f"{command}/url",
                "state_topic": state,
                "value_template": "{{ value_json.configured_url }}",
                "max": 255,
                "mode": "text",
                "icon": "mdi:web-box",
            }),
            "restart_browser": ("button", {
                "name": "Restart Browser",
                "command_topic": f"{command}/restart_browser",
                "payload_press": "PRESS",
                "entity_category": "config",
            }),
            "reinitialize_display": ("button", {
                "name": "Reinitialize Display",
                "command_topic": f"{command}/reinitialize_display",
                "payload_press": "PRESS",
                "entity_category": "config",
            }),
            "zoom": ("number", {
                "name": "Browser Zoom",
                "command_topic": f"{command}/zoom",
                "state_topic": state,
                "value_template": "{{ value_json.browser_experience.zoom }}",
                "min": 0.5,
                "max": 2.0,
                "step": 0.1,
                "mode": "slider",
                "entity_category": "config",
            }),
            "color_scheme": ("select", {
                "name": "Browser Theme",
                "command_topic": f"{command}/theme",
                "state_topic": state,
                "value_template": "{{ value_json.browser_experience.color_scheme }}",
                "options": ["auto", "light", "dark"],
                "entity_category": "config",
                "icon": "mdi:theme-light-dark",
            }),
            "page": ("select", {
                "name": "Page",
                "command_topic": f"{command}/page",
                "state_topic": state,
                "value_template": "{{ value_json.current_page }}",
                "options": ["Home"] + [
                    ("Home (page)" if str(item.get("name", "")).casefold() == "home" else str(item.get("name") or f"Page {i + 1}"))
                    for i, item in enumerate(self.cfg.get("browser", {}).get("pages", []))
                    if isinstance(item, dict) and item.get("url")
                ] + ["Custom"],
            }),
            "previous_page": ("button", {
                "name": "Previous Page",
                "command_topic": f"{command}/previous_page",
                "payload_press": "PRESS",
            }),
            "next_page": ("button", {
                "name": "Next Page",
                "command_topic": f"{command}/next_page",
                "payload_press": "PRESS",
            }),
            "idle": ("switch", {
                "name": "Idle Display Policy",
                "command_topic": f"{command}/idle",
                "state_topic": state,
                "value_template": "{{ 'ON' if value_json.idle.enabled else 'OFF' }}",
                "payload_on": "ON",
                "payload_off": "OFF",
                "entity_category": "config",
            }),
            "cpu": ("sensor", {
                "name": "CPU Usage",
                "state_topic": state,
                "value_template": "{{ value_json.cpu_percent | round(1) }}",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "entity_category": "diagnostic",
            }),
            "memory": ("sensor", {
                "name": "Memory Usage",
                "state_topic": state,
                "value_template": "{{ value_json.memory_percent | round(1) }}",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "entity_category": "diagnostic",
            }),
            "temperature": ("sensor", {
                "name": "CPU Temperature",
                "state_topic": state,
                "value_template": "{{ value_json.temperature_c }}",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
                "state_class": "measurement",
                "entity_category": "diagnostic",
            }),
        }

    def publish_discovery(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "Home Assistant plugin is disabled"}
        if not self.mqtt.connected:
            return {"ok": False, "reason": "MQTT is not connected"}
        dev = self._device()
        origin = self._origin()
        published = 0
        try:
            for object_id, (component, entity) in self._entities().items():
                payload = copy.deepcopy(entity)
                payload.update({
                    "unique_id": f"kioskctl_{self.mqtt.device_id}_{object_id}",
                    "device": dev,
                    "origin": origin,
                    "availability_topic": f"{self.mqtt.base}/availability",
                })
                topic = f"{self.prefix}/{component}/kioskctl_{self.mqtt.device_id}/{object_id}/config"
                if not self.mqtt.publish_json(topic, payload, retain=True):
                    raise RuntimeError(f"publish failed for {topic}")
                published += 1
            # Discovery may be consumed after an older retained state was read.
            # Publish a fresh retained snapshot immediately so new entities such
            # as Current URL have a value without waiting for the 15s heartbeat.
            self.mqtt.publish_json(f"{self.mqtt.base}/state", self.get_status(), retain=True)
            self.last_publish = _now()
            self.last_error = None
            self.publish_count += 1
            self.entity_count = published
            logger.info("Home Assistant: published %d discovery entities", published)
            return {"ok": True, "entities": published, "last_publish": self.last_publish}
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("Home Assistant discovery publish failed")
            return {"ok": False, "reason": str(exc), "entities": published}

    def clear_discovery(self) -> dict[str, Any]:
        if not self.mqtt.connected:
            return {"ok": False, "reason": "MQTT is not connected"}
        cleared = 0
        for object_id, (component, _entity) in self._entities().items():
            topic = f"{self.prefix}/{component}/kioskctl_{self.mqtt.device_id}/{object_id}/config"
            if self.mqtt.publish(topic, "", retain=True):
                cleared += 1
        logger.info("Home Assistant: cleared %d discovery topics", cleared)
        return {"ok": True, "cleared": cleared}

    def status(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "started": self.started,
            "discovery_prefix": self.prefix,
            "mqtt_connected": self.mqtt.connected,
            "device_id": f"kioskctl_{self.mqtt.device_id}",
            "entities": self.entity_count or len(self._entities()),
            "last_publish": self.last_publish,
            "publish_count": self.publish_count,
            "last_error": self.last_error,
        }
