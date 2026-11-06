"""Lightweight MQTT Telemetry Publisher for Home Assistant, Node-RED & IoT."""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from intelligent_tracker.events.types import BaseEvent, EntityIdentifiedEvent

logger = logging.getLogger(__name__)


class MqttPublisher:
    """
    Lightweight MQTT Telemetry Publisher for Home Assistant, Node-RED & IoT.

    Topics:
    - `tracker/{camera_id}/occupancy` (JSON with counts, retained=True)
    - `tracker/{camera_id}/events` (JSON event stream, retained=False)
    - `tracker/{camera_id}/sightings/{entity_id}` (JSON entity sighting, retained=True)
    - `tracker/{camera_id}/status` (LWT: 'online' / 'offline', retained=True)
    """

    def __init__(
        self,
        broker: Optional[str] = None,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        client_id: str = "intelligent_tracker",
        base_topic: str = "tracker",
        qos: int = 1,
        retain_occupancy: bool = True,
        retain_sightings: bool = True,
        mock: bool = False,
        stop_event: Optional[threading.Event] = None,
    ):
        self.broker = str(broker if broker is not None else os.getenv("MQTT_BROKER", "localhost"))
        self.port = int(port)
        self.username = username
        self.password = password
        self.client_id = str(client_id)
        self.base_topic = str(base_topic).rstrip("/")
        self.qos = int(qos)
        self.retain_occupancy = bool(retain_occupancy)
        self.retain_sightings = bool(retain_sightings)
        self.mock = bool(mock) or (mqtt is None)
        self._stop_event = stop_event or threading.Event()

        self._client = None
        self._connected = False
        self.published_messages: List[Dict[str, Any]] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, timeout: float = 5.0) -> bool:
        """Establish connection to MQTT broker and configure LWT."""
        if self.mock:
            self._connected = True
            return True

        if mqtt is None:
            self.mock = True
            self._connected = True
            return True

        try:
            if hasattr(mqtt, "CallbackAPIVersion"):
                self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
            else:
                self._client = mqtt.Client(client_id=self.client_id)

            if self.username and self.password:
                self._client.username_pw_set(self.username, self.password)

            status_topic = f"{self.base_topic}/system/status"
            self._client.will_set(status_topic, payload="offline", qos=self.qos, retain=True)

            def on_connect(client, userdata, flags, rc, *args, **kwargs):
                if rc == 0:
                    self._connected = True
                    client.publish(status_topic, payload="online", qos=self.qos, retain=True)
                else:
                    self._connected = False

            self._client.on_connect = on_connect
            self._client.connect(self.broker, self.port, keepalive=60)
            self._client.loop_start()

            t0 = time.time()
            while not self._connected and (time.time() - t0 < timeout):
                if self._stop_event.wait(timeout=0.05):
                    logger.info("MQTT connection attempt aborted due to stop signal")
                    self._client.loop_stop()
                    return False

            return self._connected

        except Exception as e:
            logger.warning(
                "Could not connect to MQTT broker %s:%d: %s (falling back to mock mode)",
                self.broker, self.port, e
            )
            self.mock = True
            self._connected = True
            return True

    def disconnect(self):
        """Publish offline status and disconnect from broker."""
        self._stop_event.set()
        if self._client and not self.mock:
            try:
                status_topic = f"{self.base_topic}/system/status"
                self._client.publish(status_topic, payload="offline", qos=self.qos, retain=True)
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self._connected = False

    def publish(self, topic: str, payload: Any, qos: Optional[int] = None, retain: bool = False) -> bool:
        """Publish a message to MQTT topic."""
        q = self.qos if qos is None else qos
        if not isinstance(payload, str):
            payload_str = json.dumps(payload, default=str)
        else:
            payload_str = payload

        self.published_messages.append({
            "topic": topic,
            "payload": payload_str,
            "qos": q,
            "retain": retain,
            "timestamp": time.time(),
        })

        if self.mock or not self._client or not self._connected:
            return True

        try:
            info = self._client.publish(topic, payload=payload_str, qos=q, retain=retain)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.warning("Failed to publish to MQTT topic %s: %s", topic, e)
            return False

    def publish_occupancy(
        self,
        camera_id: str,
        zone_occupancy: Dict[str, int],
        total_tracks: int,
        timestamp: Optional[float] = None,
    ) -> bool:
        """
        Publish camera occupancy telemetry (Home Assistant compatible).
        Topic: `tracker/{camera_id}/occupancy`
        """
        topic = f"{self.base_topic}/{camera_id}/occupancy"
        payload = {
            "camera_id": camera_id,
            "timestamp": timestamp or time.time(),
            "total_tracks": int(total_tracks),
            "zones": dict(zone_occupancy),
        }
        return self.publish(topic, payload, retain=self.retain_occupancy)

    def publish_event(self, event: BaseEvent) -> bool:
        """
        Publish an event stream message.
        Topic: `tracker/{camera_id}/events`
        """
        topic = f"{self.base_topic}/{event.camera_id}/events"
        payload = event.to_dict(include_snapshot=False)
        return self.publish(topic, payload, retain=False)

    def publish_sighting(
        self,
        camera_id: str,
        entity_id: int,
        name: str,
        category: str,
        zone_id: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> bool:
        """
        Publish last-known location of recognized entity.
        Topic: `tracker/{camera_id}/sightings/{entity_id}`
        """
        topic = f"{self.base_topic}/{camera_id}/sightings/{entity_id}"
        payload = {
            "camera_id": camera_id,
            "entity_id": int(entity_id),
            "name": str(name),
            "category": str(category),
            "zone_id": zone_id,
            "timestamp": timestamp or time.time(),
        }
        return self.publish(topic, payload, retain=self.retain_sightings)

    def send(self, event: BaseEvent) -> bool:
        """Convenience subscriber method for EventBus."""
        ok = self.publish_event(event)
        if isinstance(event, EntityIdentifiedEvent) and event.entity_id:
            self.publish_sighting(
                camera_id=event.camera_id,
                entity_id=event.entity_id,
                name=event.name,
                category=event.category,
                zone_id=event.zone_id,
                timestamp=event.timestamp,
            )
        return ok

