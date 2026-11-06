"""HTTP POST Webhook Dispatcher with retry logic and exponential backoff."""

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional, Union

try:
    import requests
except ImportError:
    requests = None

try:
    import urllib.request as urllib_request
    import urllib.error as urllib_error
except ImportError:
    urllib_request = None
    urllib_error = None

from intelligent_tracker.events.types import BaseEvent

logger = logging.getLogger(__name__)


class WebhookDispatcher:
    """
    HTTP POST Webhook Dispatcher with retry logic and exponential backoff.

    Delivers JSON payloads on tripwire crosses, zone intrusions, capacity
    threshold breaches, or tagged entity sightings.
    """

    def __init__(
        self,
        url: str,
        auth_header: Optional[Union[str, Dict[str, str]]] = None,
        secret_key: Optional[str] = None,
        timeout: float = 5.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        include_snapshot: bool = True,
        event_types: Optional[List[str]] = None,
        headers: Optional[Dict[str, str]] = None,
        custom_headers: Optional[Dict[str, str]] = None,
    ):
        self.url = str(url)
        self.auth_header = auth_header
        self.secret_key = str(secret_key) if secret_key else None
        self.timeout = float(timeout)
        self.max_retries = max(1, int(max_retries))
        self.backoff_factor = float(backoff_factor)
        self.include_snapshot = bool(include_snapshot)
        self.event_types = set(event_types) if event_types else None
        self.custom_headers = dict(headers or custom_headers or {})

        # Telemetry metrics
        self.sent_count = 0
        self.failed_count = 0
        self.retry_count = 0
        self.last_status_code = 0
        self.last_error = None
        self.history: List[Dict[str, Any]] = []

    def build_payload(self, event: BaseEvent) -> Dict[str, Any]:
        """Construct standard JSON webhook payload with ISO-8601 UTC timestamp."""
        ts = event.timestamp
        if isinstance(ts, (int, float)):
            try:
                iso_ts = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                iso_ts = str(ts)
        else:
            iso_ts = str(ts)

        base_dict = event.to_dict(include_snapshot=False)
        payload = {
            "camera_id": event.camera_id,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "timestamp": iso_ts,
            "timestamp_epoch": event.timestamp,
            "zone_id": getattr(event, "zone_id", None),
            "entity_id": getattr(event, "entity_id", None),
            "entity_name": getattr(event, "entity_name", getattr(event, "name", None)),
            "severity": getattr(event, "severity", "info"),
            "data": base_dict,
        }
        if self.include_snapshot and event.snapshot_base64:
            payload["snapshot"] = event.snapshot_base64
            payload["snapshot_base64"] = event.snapshot_base64

        return payload

    def _prepare_headers(self, json_data: Optional[bytes] = None) -> Dict[str, str]:
        """Prepare request headers including authentication and HMAC-SHA256 signature."""
        h = {
            "Content-Type": "application/json",
            "User-Agent": "IntelligentTracker-Webhook/1.0",
        }
        h.update(self.custom_headers)

        if self.secret_key and json_data is not None:
            sig = hmac.new(self.secret_key.encode("utf-8"), json_data, hashlib.sha256).hexdigest()
            h["X-Tracker-Signature"] = sig

        if self.auth_header:
            if isinstance(self.auth_header, dict):
                h.update(self.auth_header)
            elif isinstance(self.auth_header, str):
                if self.auth_header.lower().startswith(("bearer ", "token ", "basic ")):
                    h["Authorization"] = self.auth_header
                else:
                    h["Authorization"] = f"Bearer {self.auth_header}"
        return h

    def send(self, event: BaseEvent) -> bool:
        """
        Send event via HTTP POST with retries and exponential backoff.

        :param event: BaseEvent to dispatch.
        :return: True if delivered successfully (HTTP 2xx), False otherwise.
        """
        if self.event_types and event.event_type not in self.event_types:
            return False

        payload = self.build_payload(event)
        json_data = json.dumps(payload).encode("utf-8")
        headers = self._prepare_headers(json_data=json_data)

        for attempt in range(1, self.max_retries + 1):
            try:
                # 1. Try requests if installed
                if requests is not None:
                    resp = requests.post(
                        self.url,
                        data=json_data,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    self.last_status_code = resp.status_code
                    if 200 <= resp.status_code < 300:
                        self.sent_count += 1
                        self.history.append({"event_id": event.event_id, "status": resp.status_code})
                        return True
                    else:
                        raise RuntimeError(f"HTTP status {resp.status_code}")

                # 2. Standard library urllib fallback
                elif urllib_request is not None:
                    req = urllib_request.Request(self.url, data=json_data, headers=headers, method="POST")
                    with urllib_request.urlopen(req, timeout=self.timeout) as resp:
                        code = resp.getcode()
                        self.last_status_code = code
                        if 200 <= code < 300:
                            self.sent_count += 1
                            self.history.append({"event_id": event.event_id, "status": code})
                            return True
                        else:
                            raise RuntimeError(f"HTTP status {code}")
                else:
                    raise RuntimeError("Neither requests nor urllib available.")

            except Exception as e:
                self.last_error = str(e)
                if attempt < self.max_retries:
                    self.retry_count += 1
                    sleep_time = self.backoff_factor * (2 ** (attempt - 1))
                    time.sleep(sleep_time)
                else:
                    self.failed_count += 1
                    logger.warning("Webhook failed to %s after %d retries: %s", self.url, attempt, e)

        return False

