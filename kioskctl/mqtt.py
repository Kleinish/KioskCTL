from __future__ import annotations

import json
import logging
import socket
import threading
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger("kioskctl.mqtt")

try:
    import paho.mqtt.client as mqtt
except Exception:  # optional at runtime
    mqtt = None

ConnectCallback = Callable[["MQTTBridge"], None]
MessageCallback = Callable[[str, str], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MQTTBridge:
    """Generic MQTT transport for kioskctl.

    The core owns broker connectivity, kioskctl state/availability and generic
    command topics. Integrations such as Home Assistant register connection and
    subscription callbacks without embedding integration-specific discovery in
    this transport.
    """

    def __init__(self, cfg: dict[str, Any], get_status: Callable[[], dict[str, Any]], handle_command: Callable[[str, str], None]):
        self.cfg = cfg
        self.get_status = get_status
        self.handle_command = handle_command
        self.client = None
        self.thread = None
        self.stop_event = threading.Event()
        self.device_id = socket.gethostname().replace(".", "_").lower()
        self._lock = threading.RLock()
        self._connect_listeners: list[ConnectCallback] = []
        self._subscriptions: dict[str, list[MessageCallback]] = {}
        self._connected = False
        self._last_connect: str | None = None
        self._last_disconnect: str | None = None
        self._last_error: str | None = None
        self._published = 0
        self._received = 0

    @property
    def base(self) -> str:
        name = str(self.cfg["device"]["name"]).replace(" ", "_").lower()
        return f"{self.cfg['mqtt'].get('base_topic', 'kioskctl')}/{name}"

    @property
    def client_id(self) -> str:
        return f"kioskctl-{self.device_id}"

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    def add_connect_listener(self, callback: ConnectCallback) -> None:
        with self._lock:
            if callback not in self._connect_listeners:
                self._connect_listeners.append(callback)

    def subscribe(self, topic: str, callback: MessageCallback) -> None:
        with self._lock:
            callbacks = self._subscriptions.setdefault(topic, [])
            if callback not in callbacks:
                callbacks.append(callback)
            client = self.client
            connected = self._connected
        if connected and client is not None:
            client.subscribe(topic)
            logger.info("MQTT: subscribed %s", topic)

    def publish(self, topic: str, payload: str, *, retain: bool = False) -> bool:
        with self._lock:
            client = self.client
            connected = self._connected
        if client is None or not connected:
            return False
        try:
            info = client.publish(topic, payload, retain=retain)
            if getattr(info, "rc", 0) != 0:
                raise RuntimeError(f"publish rc={info.rc}")
            with self._lock:
                self._published += 1
            return True
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            logger.exception("MQTT publish failed for %s", topic)
            return False

    def publish_json(self, topic: str, payload: dict[str, Any], *, retain: bool = False) -> bool:
        return self.publish(topic, json.dumps(payload, separators=(",", ":")), retain=retain)

    def start(self) -> None:
        if not self.cfg["mqtt"].get("enabled"):
            logger.info("MQTT: disabled")
            return
        if mqtt is None:
            with self._lock:
                self._last_error = "paho-mqtt is unavailable"
            logger.error("MQTT: enabled but paho-mqtt is unavailable")
            return
        if self.client is not None:
            return
        self.stop_event.clear()
        host = str(self.cfg["mqtt"].get("host", "127.0.0.1"))
        port = int(self.cfg["mqtt"].get("port", 1883))
        logger.info("MQTT: connecting to %s:%s as %s", host, port, self.client_id)
        mc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
        user = self.cfg["mqtt"].get("username")
        if user:
            mc.username_pw_set(user, self.cfg["mqtt"].get("password", ""))
        mc.on_connect = self._on_connect
        mc.on_disconnect = self._on_disconnect
        mc.on_connect_fail = self._on_connect_fail
        mc.on_message = self._on_message
        mc.will_set(f"{self.base}/availability", "offline", retain=True)
        self.client = mc
        try:
            mc.connect_async(host, port, 30)
            mc.loop_start()
        except Exception as exc:
            self.client = None
            with self._lock:
                self._last_error = str(exc)
            logger.exception("MQTT: startup failed")
            return
        self.thread = threading.Thread(target=self._publisher, daemon=True, name="kioskctl-mqtt-publisher")
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        with self._lock:
            client = self.client
        if client:
            try:
                if self.connected:
                    client.publish(f"{self.base}/availability", "offline", retain=True)
                client.disconnect()
                client.loop_stop()
            except Exception:
                logger.exception("MQTT: failed during shutdown")
        with self._lock:
            self.client = None
            self._connected = False
        thread = self.thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        self.thread = None

    def restart(self) -> None:
        self.stop()
        self.stop_event.clear()
        self.start()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": bool(self.cfg.get("mqtt", {}).get("enabled")),
                "library_available": mqtt is not None,
                "connected": self._connected,
                "host": str(self.cfg.get("mqtt", {}).get("host", "")),
                "port": int(self.cfg.get("mqtt", {}).get("port", 1883)),
                "username": str(self.cfg.get("mqtt", {}).get("username", "")),
                "password_set": bool(self.cfg.get("mqtt", {}).get("password", "")),
                "base_topic": str(self.cfg.get("mqtt", {}).get("base_topic", "kioskctl")),
                "device_topic": self.base,
                "client_id": self.client_id,
                "last_connect": self._last_connect,
                "last_disconnect": self._last_disconnect,
                "last_error": self._last_error,
                "published_messages": self._published,
                "received_messages": self._received,
                "subscriptions": sorted(self._subscriptions.keys()),
            }

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        failure = bool(getattr(reason_code, "is_failure", False))
        if failure:
            with self._lock:
                self._connected = False
                self._last_error = str(reason_code)
            logger.error("MQTT: connection rejected: %s", reason_code)
            return
        with self._lock:
            self._connected = True
            self._last_connect = _now()
            self._last_error = None
            subscriptions = list(self._subscriptions.keys())
            listeners = list(self._connect_listeners)
        logger.info("MQTT: connected to %s:%s", self.cfg["mqtt"].get("host"), self.cfg["mqtt"].get("port", 1883))
        client.publish(f"{self.base}/availability", "online", retain=True)
        client.subscribe(f"{self.base}/command/+")
        logger.info("MQTT: subscribed %s/command/+", self.base)
        for topic in subscriptions:
            client.subscribe(topic)
            logger.info("MQTT: subscribed %s", topic)
        try:
            client.publish(f"{self.base}/state", json.dumps(self.get_status()), retain=True)
        except Exception:
            logger.exception("MQTT: initial state publish failed")
        for callback in listeners:
            try:
                callback(self)
            except Exception:
                logger.exception("MQTT connect listener failed")

    def _on_connect_fail(self, client, userdata):
        with self._lock:
            self._connected = False
            self._last_error = "connection failed"
        logger.warning("MQTT: connection attempt failed")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        with self._lock:
            self._connected = False
            self._last_disconnect = _now()
            if str(reason_code).lower() not in {"normal disconnection", "success", "0"}:
                self._last_error = str(reason_code)
        logger.info("MQTT: disconnected: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        topic = str(msg.topic)
        payload = msg.payload.decode(errors="replace")
        with self._lock:
            self._received += 1
            subscriptions = [(pattern, list(callbacks)) for pattern, callbacks in self._subscriptions.items()]
        if topic.startswith(f"{self.base}/command/"):
            command = topic.rsplit("/", 1)[-1]
            try:
                self.handle_command(command, payload)
            except Exception as exc:
                logger.exception("MQTT command %s failed", command)
                self.publish(f"{self.base}/last_error", str(exc), retain=False)
        if mqtt is not None:
            for pattern, callbacks in subscriptions:
                try:
                    matched = mqtt.topic_matches_sub(pattern, topic)
                except Exception:
                    matched = pattern == topic
                if matched:
                    for callback in callbacks:
                        try:
                            callback(topic, payload)
                        except Exception:
                            logger.exception("MQTT subscriber failed for %s", topic)

    def _publisher(self):
        # Publish immediately on connect in _on_connect, then refresh every 15s.
        while not self.stop_event.wait(15):
            if self.connected:
                try:
                    self.publish(f"{self.base}/state", json.dumps(self.get_status()), retain=True)
                except Exception:
                    logger.exception("MQTT status publish failed")
