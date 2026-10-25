========================================================================
Event Dispatching & Alerting System (Webhooks, Telegram & MQTT)
========================================================================

The **Event Dispatching & Alerting System** provides a high-performance, asynchronous
event bus and multi-channel alerting pipeline for retail telemetry, access control,
and physical security.

It bridges computer vision tracking events (zone entry/exit, tripwire crossings,
occupancy thresholds, and visual Re-ID recognitions) to external messaging brokers,
security operations centers (SOC), home automation controllers (Home Assistant, Node-RED),
and mobile alerting bots (Telegram).

Key Components
==============

1. Centralized Event Bus (``EventBus``)
---------------------------------------
Thread-safe Publish/Subscribe event broker operating in asynchronous worker threads:

- **Zero Event Loss**: Internal thread-safe ``Queue`` ensures high-speed tracking loops never block on network operations.
- **Selective Subscription**: Subscribe to specific typed events (e.g. ``IntrusionAlert``), custom predicate filters (e.g. ``lambda ev: ev.zone_id == "vault"``), or universal event streams.
- **Error Isolation**: Failing or slow subscriber callbacks are isolated via exception boundaries, preventing worker crashes.
- **Auditing Ring Buffer**: In-memory historical ring buffer (default 500 events) for querying recent occurrences and telemetry summaries.

2. Typed Event Contracts
------------------------
Strictly typed dataclasses standardizing telemetry payloads across all channels:

- **``BaseEvent``**: Base contract with UUID ``event_id``, Unix ``timestamp``, ``camera_id``, optional JPEG ``snapshot_base64``, and extensible ``metadata``.
- **``ZoneEvent``**: Emitted on zone interactions (``"enter"``, ``"exit"``, ``"dwell"``) with dwell duration and bounding box geometry.
- **``TripwireCrossEvent``**: Emitted when crossing a virtual line with trajectory direction (``"in"``, ``"out"``).
- **``IntrusionAlert``**: High-priority alert triggered on unauthorized access into restricted zones or after-hours breaches.
- **``OccupancyThresholdEvent``**: Capacity alert emitted when a zone exceeds (or clears) its configured ``capacity_limit``.
- **``EntityIdentifiedEvent``**: Visual recognition notification containing entity ID, canonical name, category, and cosine similarity.
- **``RestrictedEntityAlert``**: Critical security alert emitted when a blacklisted, banned, or restricted subject is spotted.

3. HTTP POST Webhook Dispatcher (``WebhookDispatcher``)
-------------------------------------------------------
Delivers structured JSON payloads to REST APIs and webhook receivers:

- **Exponential Backoff Retries**: Up to 3 automatic retries with configurable exponential delay (``backoff_factor * (2 ** attempt)``).
- **Authentication**: Supports Bearer tokens, API keys, and custom authorization headers.
- **Snapshot Attachment**: Inlines base64 JPEG crops of detected targets or full scene frames.
- **Telemetry Metrics**: Tracks ``sent_count``, ``failed_count``, ``retry_count``, and ``last_status_code``.

4. Telegram Bot Dispatcher (``TelegramDispatcher``)
---------------------------------------------------
Instant push notifications to mobile and desktop Telegram clients:

- **Visual Alert Banners**: Rich Markdown alerts formatted with status emojis (🚨, ⚠️, 👤, 🛑), camera IDs, timestamps, and zone labels.
- **Photo Attachments**: Directly uploads visual snapshots via Telegram Bot API ``sendPhoto``.
- **Cooldown Rate Limiting**: Deduplicates alerts per ``(event_type, zone, entity)`` within a configurable cooldown window (e.g. 60s) to prevent notification fatigue.
- **Interactive `/status` Responder**: Responds to incoming commands (``/status``, ``/occupancy``, ``/help``) with live zone occupancy counts, tripwire tallies, and recent security alerts.
- **Offline Mock Mode**: Allows headless CI and local testing without live bot credentials.

5. MQTT Telemetry Publisher (``MqttPublisher``)
-----------------------------------------------
Lightweight IoT telemetry for Home Assistant, Node-RED, and MQTT brokers:

- **Occupancy Telemetry**: Published to ``tracker/{camera_id}/occupancy`` as JSON with total and per-zone counts (retained).
- **Event Stream**: Published to ``tracker/{camera_id}/events`` on every trigger (unretained).
- **Last Known Sighting**: Published to ``tracker/{camera_id}/sightings/{entity_id}`` with entity metadata and zone location (retained).
- **Last Will & Testament (LWT)**: Publishes ``"online"`` on startup and ``"offline"`` to ``tracker/system/status`` upon unexpected connection drop.
- **Paho MQTT 2.x & 1.x**: Compatible with both modern ``CallbackAPIVersion.VERSION2`` and legacy Paho clients.

6. Quiet Hours & Alert Rule Engine (``AlertRuleEngine``)
--------------------------------------------------------
Rule evaluation engine for context-aware security logic:

- **``QuietHours``**: Evaluates time-of-day schedules including overnight spans crossing midnight (e.g. 22:00 to 06:00) and day-of-week filters.
- **``AlertRule``**: Matches events on zone, action, entity category (e.g. ``"restricted"``, ``"unknown"``), minimum dwell time, and quiet hours.
- **Automatic Derivation**: Evaluates raw zone and track events to automatically emit ``IntrusionAlert`` or ``RestrictedEntityAlert`` events with attached frame snapshots.

Configuration Example (``configs/alert_demo.yaml``)
===================================================

.. code-block:: yaml

   alerting:
     camera_id: "cam_warehouse_01"

     webhooks:
       - url: "http://127.0.0.1:8080/events/webhook"
         auth_token: "secret_webhook_token_abc123"
         timeout: 3.0
         max_retries: 2
         include_snapshot: true
         event_types: ["intrusion_alert", "restricted_entity_alert", "occupancy_threshold"]

     telegram:
       enabled: true
       token: "mock"        # Set to bot token or "mock" for offline testing
       chat_id: "123456789"
       cooldown: 30.0
       include_snapshot: true
       mock: true

     mqtt:
       enabled: true
       broker: "localhost"
       port: 1883
       base_topic: "tracker"
       client_id: "intelligent_tracker_demo"
       qos: 1
       retain_occupancy: true
       retain_sightings: true
       mock: true

     rules:
       - name: vault_intrusion_alert
         zone_id: "restricted_vault"
         event_types: ["zone_enter", "enter", "dwell"]
         categories: ["restricted", "unknown"]
         cooldown: 20.0
         severity: "critical"
         message: "Security Breach: Unauthorized entity entered restricted vault!"

       - name: vault_quiet_hours
         zone_id: "restricted_vault"
         quiet_hours_only: true
         quiet_hours:
           start: "22:00"
           end: "06:00"
         severity: "critical"
         message: "Perimeter Alert: Vault access detected during quiet hours schedule!"

       - name: lobby_overcrowding
         zone_id: "public_lobby"
         event_types: ["occupancy_threshold"]
         severity: "warning"
         message: "Occupancy limit exceeded in public lobby area."

Verification & Execution
========================

Automated Unit Test Suite
-------------------------

Execute the dedicated Milestone 5 test suite (18 unit tests, local HTTP echo server, mock MQTT, and rules):

.. code-block:: powershell

   .\.venv\Scripts\python.exe -m tests.test_events

Live Alerting Demonstration
---------------------------

Run tracking with full alerting pipeline in headless mode:

.. code-block:: powershell

   .\.venv\Scripts\python.exe main.py --config configs/alert_demo.yaml --headless --frames 30
