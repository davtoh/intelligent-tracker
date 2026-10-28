.. _enterprise_hub_integration:

Enterprise Cloud Hub Integration & Edge Protocol
================================================

This document specifies the integration architecture between the edge microservice (**intelligent_tracker**) and the central enterprise cloud management platform (**davtoh/enterprise-website**).

Overview & System Architecture
------------------------------

When deployed in physical environments (retail stores, warehouses, checkpoints, or corporate campuses), **intelligent_tracker** functions as an autonomous Edge AI Vision appliance. It handles local camera acquisition, high-framerate multi-object inference, Re-ID feature extraction, and spatial rules, while synchronizing with the central Enterprise Cloud Hub:

.. code-block:: text

    +-------------------------------------------------------+
    | Edge Vision Node (intelligent_tracker)                |
    | - RTSP/USB Acquisition & Multi-Camera Pool            |
    | - YOLOv8/v11 + OSNet Re-ID + Spatial Engine           |
    | - Embedded SQLite (TrackerDB) with Offline Cache      |
    | - FastAPI Daemon: MJPEG Streaming & Telemetry REST    |
    +-------------------------------------------------------+
           |                    ^                   ^
           | (Outbound Webhook) | (Range Requests)  | (Delta Sync)
           v                    v                   v
    +-------------------------------------------------------+
    | Enterprise Cloud Hub (enterprise-website)             |
    | - /api/v1/security/events/ (HMAC-SHA256 Webhook)      |
    | - /api/v1/gallery/stream/ (Zero-Copy Proxy)           |
    | - /api/v1/security/stream/telemetry/ (Canvas Overlay) |
    | - /api/v1/security/whitelist/ (ETag Delta Sync)       |
    | - /api/v1/security/access/ (Outbox Ingestion)         |
    +-------------------------------------------------------+

1. Edge-to-Hub Security Webhooks (HMAC-SHA256)
-----------------------------------------------

Critical security events (perimeter intrusions, tripwire crosses, restricted identity sightings, occupancy spikes) are delivered in real-time to the Hub:

* **Endpoint:** ``POST /api/v1/security/events/``
* **Authentication:** HMAC-SHA256 signature transmitted in the ``X-Tracker-Signature`` HTTP header.
* **Algorithm:** The hex digest of the HMAC computed over the raw UTF-8 JSON request body using the shared site secret:

.. code-block:: python

    import hmac
    import hashlib

    def compute_signature(secret: str, body_bytes: bytes) -> str:
        return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

* **Standardized Webhook Payload:**

.. code-block:: json

    {
      "event_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "event_type": "IntrusionAlert",
      "site_id": 1,
      "camera_id": "cam_01",
      "timestamp": "2026-10-28T14:30:00Z",
      "severity": "critical",
      "zone_id": "vault_perimeter",
      "entity_name": "Unknown Suspect",
      "snapshot_base64": "/9j/4AAQSkZJRgABAQ...",
      "metadata": {
        "confidence": 0.94,
        "dwell_time": 8.5,
        "ground_pos": [4.2, 12.8]
      }
    }

2. Zero-Copy Video Evidence Streaming (HTTP 206)
-------------------------------------------------

To prevent duplicating large MP4 files across WAN links, video clips remain stored on the local edge disk:

* **Edge Endpoint:** ``GET /videos/{filename}``
* **Range Request Support:** Served via Starlette ``FileResponse``, supporting standard HTTP ``Range: bytes=start-end`` headers and returning ``HTTP 206 Partial Content``.
* **Hub Streaming Reverse Proxy:** The Hub exposes ``GET /api/v1/gallery/stream/<video_id>/`` which transparently proxies Range requests to the edge node, allowing operators on the central web console to scrub and seek through edge recordings without public LAN exposure.

3. Live Stream Proxy & HTTP Telemetry
-------------------------------------

* **MJPEG Live Feed:** ``GET /stream/{camera_id}`` generates continuous ``multipart/x-mixed-replace; boundary=frame`` frames.
* **REST Telemetry Snapshot:** ``GET /api/cameras/{camera_id}/telemetry`` returns the current detection bounding boxes and tracking states for central HTML5 Canvas overlays:

.. code-block:: json

    {
      "camera_id": "cam_01",
      "status": "online",
      "fps": 29.8,
      "resolution": "1920x1080",
      "active_tracks": [
        {
          "id": 14,
          "bbox": [320, 180, 510, 640],
          "centroid": [415.0, 410.0],
          "ground_pos": [3.5, 8.2],
          "velocity": [0.15, -0.02],
          "label": "person",
          "confidence": 0.92,
          "dwell_time": 14.2,
          "entity_name": "Alice Johnson",
          "category": "vip"
        }
      ],
      "zones": [
        {
          "name": "Entrance Lobby",
          "occupancy": 3,
          "capacity_limit": 10
        }
      ],
      "tripwires": []
    }

4. Offline-First Cache Schema & Local Whitelist
-----------------------------------------------

To ensure autonomous gate operation during WAN outages, the local SQLite database (``TrackerDB``) maintains an offline mirror of authoritative credentials synchronized from the Hub:

* **Sync State Tracking (``tracker_sync_state``):** Tracks ``last_etag``, ``last_sync_timestamp``, and ``active_whitelist_count``.
* **Local Whitelist (``local_whitelist``):** Stores normalized license plates, pre-computed 512-d Re-ID embeddings, clearance tiers (``VIP``, ``STAFF``, ``CONTRACTOR``, ``VISITOR``, ``RESTRICTED``, ``BANNED``), validity windows (``valid_from``, ``valid_until``), and ban flags.
* **Offline Access Outbox (``offline_access_queue``):** Buffers gate access events when offline, flushing them to ``POST /api/v1/security/access/`` upon WAN restoration.

5. Edge VMS Dashboard Modernization
-----------------------------------

The edge web dashboard (``/``) is upgraded to provide matching ergonomics and responsiveness:

* **Fully Responsive Navigation:** Auto-scrolling horizontal tab bar with snap scrolling on mid screens and a slide-out hamburger drawer on mobile/tablet viewports (<1024px).
* **Standardized Modal Dialog Architecture:** Fixed headers, sticky action footers, and scrollable body containers with CSS scroll chaining containment (``overscroll-behavior: contain``), preventing form overflow across all screen sizes.
* **Elimination of Cumbersome Alert Prompts:** Replaced sequential browser ``prompt()`` and ``confirm()`` alert chains with dedicated in-page modal forms (Zone Builder, Tripwire Builder, Homography Calibration, Spatial Topology Transitions, Entity Quick-Enroll) and non-blocking toast notifications.
* **Bidirectional Hash Routing:** Synchronizes active tabs and dialog states to the URL (``#live``, ``#videos``, ``#gallery``, ``#cameras``), preserving deep links and browser Back/Forward navigation.
* **Foolproof Stream Reconnect:** Automatic detachment and clean reconnection of MJPEG streams on tab switching, eliminating broken image states.

