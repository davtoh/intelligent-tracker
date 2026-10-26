.. _dashboard:

Web Analytics Dashboard
=======================

The **Intelligent Tracker Web Dashboard** is a real-time, responsive single-page monitoring platform
built on **FastAPI**, **HTML5/Canvas**, **WebSockets**, and **Chart.js**. It provides multi-camera live video streaming,
interactive click-to-tag bounding box enrollment, visual Re-ID gallery browsing, historical sighting search, and security telemetry.


Architecture Overview
---------------------

.. code-block:: text

    +-------------------+       MJPEG (25 FPS)       +-----------------------+
    |   Camera Stream   | =========================> |  <img> Video Canvas   |
    |  (RTSP / Webcam)  |                            | (Interactive Overlay) |
    +-------------------+                            +-----------------------+
              |                                                  ^
              v                                                  |
    +-------------------+       WebSocket (10 Hz)                |
    |   StreamManager   | ---------------------------------------+
    |  (Worker Thread)  |   JSON Telemetry: Tracks, Zones, Alerts
    +-------------------+
              |
              +--------> TrackerDB (SQLite: Entities & Sightings)
              |
              +--------> EventBus (Pub/Sub: Webhooks, Telegram, MQTT)

Key Capabilities
----------------

1. **Live MJPEG Video Stream**:
   Zero-client-dependency streaming over HTTP standard multipart boundary. Accessible directly in any modern browser.

2. **Interactive Click-to-Tag Enrollment**:
   Hovering over any active track on the live video highlights the entity bounding box.
   Clicking directly on the box opens a quick enrollment modal to register their name, category (`staff`, `vip`, `restricted`, `customer`),
   and security notes. A crop snapshot is saved, the Re-ID embedding vector is computed, and the identity is instantly recognized.

3. **Entity Gallery View**:
   Browse all registered people, vehicles, or assets with category badges, total appearance counts,
   associated feature signatures, and thumbnail photos. Supports category filtering and full-text search.

4. **Sighting Timeline Player**:
   Filter sighting records across time ranges, camera sources, and spatial zones.
   Each entry features high-resolution thumbnail evidence, timestamp, match confidence score, and zone dwell info.

5. **Spatial Density Heatmap**:
   Toggle real-time false-color density overlay directly on the live camera stream or inspect accumulated pedestrian hotspots.

6. **Real-time Security Alerts Log**:
   Instant toast notifications for critical events (`IntrusionAlert`, `RestrictedEntityAlert`, `OccupancyThresholdEvent`).

REST & WebSocket API Reference
------------------------------

Streaming Endpoints
~~~~~~~~~~~~~~~~~~~

.. http:get:: /stream/{camera_id}

   Yields live multipart MJPEG video stream: ``multipart/x-mixed-replace; boundary=frame``.

.. http:websocket:: /ws/{camera_id}

   Bidirectional WebSocket connection pushing real-time telemetry JSON packets:

   .. code-block:: json

      {
        "camera_id": "cam_01",
        "status": "online",
        "fps": 28.4,
        "frame_count": 1420,
        "active_tracks": [
          {
            "id": 12,
            "bbox": [120, 80, 65, 140],
            "label": "person",
            "confidence": 0.94,
            "dwell_time": 8.2,
            "entity_name": "Alice Guard",
            "category": "staff",
            "state": "confirmed"
          }
        ],
        "zones": [
          {
            "name": "Restricted Vault",
            "occupancy": 0,
            "capacity_limit": 1,
            "is_breached": false
          }
        ],
        "tripwires": [
          {
            "name": "Entrance",
            "in_count": 14,
            "out_count": 12
          }
        ]
      }

REST API Endpoints
~~~~~~~~~~~~~~~~~~

- ``GET /cameras``: Returns list of configured camera feeds and online statuses.
- ``GET /zones``: Returns configured zones with current occupancy and capacity limits.
- ``GET /analytics/heatmap``: Returns accumulated spatial heatmap as JPEG image or JSON density matrix.
- ``POST /analytics/heatmap/toggle``: Toggles heatmap overlay on live stream.
- ``GET /entities``: List registered entities with appearance counts, categories, and thumbnail URLs.
- ``POST /entities``: Register a new identity into the database.
- ``GET /entities/{entity_id}``: Retrieve single entity details, signatures, and sighting history.
- ``DELETE /entities/{entity_id}``: Delete entity and cascade remove signatures.
- ``GET /sightings``: Query sighting audit trail by entity, zone, or date/time range.
- ``GET /events``: Retrieve recent security and tracking alerts from EventBus.
- ``POST /tag``: Interactive click-to-tag bounding box endpoint.
- ``GET /status``: System hardware telemetry (CPU %, RAM %, active pipeline FPS, memory).

Quickstart
----------

To launch the dashboard server locally:

.. code-block:: bash

   # Start Uvicorn ASGI server
   python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000 --reload

Open your browser at ``http://localhost:8000``.
