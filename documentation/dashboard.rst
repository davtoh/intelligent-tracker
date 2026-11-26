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

1. **Live MJPEG Video Stream & Annotation Mode Toggle**:
   Zero-client-dependency streaming over HTTP standard multipart boundary. The primary 1x1 Live Monitor viewport defaults to ``?annotated=false`` (un-burned video frames with crisp client-side ``UnifiedCanvasOverlay`` bounding boxes and ROI click-to-tag hit-testing) and includes an opt-in HUD toggle (`🎯 Canvas Boxes` vs `🔥 Burned Boxes`, persisted in ``localStorage``) to switch to ``?annotated=true`` server-burned overlays while automatically suppressing duplicate client canvas boxes.

2. **Live Monitor vs. Video Studio Synchronization & Pre-Indexed File Replay**:
   ``AsyncInferenceWorker`` stamps ``inference_frame_seq``, ``inference_timestamp``, and ``inference_lag_ms`` onto live step results and clears cached detections whenever ``run_vision`` is disabled. When a camera is backed by a local video file with a completed ``TrackerDB`` ``video_runs`` detection stream, ``CachedReplayProvider`` (wrapping ``FileDetectionReplayProvider``) replays frame-aligned detections with ``0.0 ms`` inference lag and **0 GPU/scheduler slots** while running full live rule/alarm evaluation via ``evaluate_tracks_governance()`` (zones, tripwires, RSAC, pet whitelist, ``EventBus``, and ``WorldEntityBridge``) with automatic video-loop wrap-around state reset.

3. **Resource-Aware Analytics Scheduler (``P0/P1/P2``, ``MotionGate`` & 3-Stage Load Shedding)**:
   ``AnalyticsScheduler`` arbitrates CPU/GPU inference budgets across all pooled cameras to guarantee ``motion -> alarm <= 2.0 s`` on every ``armed`` camera:

   - **P0 (12–15 FPS)**: Focused live camera, actively recording cameras, and any armed camera inside its ``15.0 s`` active-alarm follow-up hold.
   - **P1 (1.0 FPS idle floor -> 8.0 FPS motion burst)**: Unfocused ``armed`` cameras gated by a ``< 0.2 ms`` ``64x36`` luma ``MotionGate`` with immediate first-frame slot submission and ``dt``-aware tracker persistence.
   - **P2 (1.0 FPS in ``full_realtime``, 0 FPS in ``focus_only``)**: Unarmed background cameras.
   - **3-Stage Load Shedding**: Under ``ELEVATED`` pressure (``> 100 ms`` EWMA latency or ``> 80%`` budget utilization), P2 sheds to ``0 FPS`` and P1 burst steps down to ``4.0 FPS``; under ``CRITICAL`` pressure (``> 250 ms``), P0 caps at ``8.0 FPS`` while protecting the ``P1 >= 1.0 FPS`` armed floor. ``scheduler_hud.js`` surfaces live tier pills (``P0 LIVE``, ``P1 MOTION``, ``P1 IDLE 1FPS``, ``P2 BG``, ``ZERO-GPU REPLAY``) and load-shedding warnings in the Live Monitor HUD.

3. **Interactive Click-to-Tag Enrollment**:
   Hovering over any active track on the live video highlights the entity bounding box.
   Clicking directly on the box opens a quick enrollment modal to register their name, category (`staff`, `vip`, `restricted`, `customer`),
   and security notes. A crop snapshot is saved, the Re-ID embedding vector is computed, and the identity is instantly recognized.

4. **Entity Gallery View**:
   Browse all registered people, vehicles, or assets with category badges, total appearance counts,
   associated feature signatures, and thumbnail photos. Supports category filtering and full-text search.

5. **Sighting Timeline Player**:
   Filter sighting records across time ranges, camera sources, and spatial zones.
   Each entry features high-resolution thumbnail evidence, timestamp, match confidence score, and zone dwell info.

6. **Spatial Density Heatmap**:
   Toggle real-time false-color density overlay directly on the live camera stream or inspect accumulated pedestrian hotspots.

7. **Real-time Security Alerts Log**:
   Instant toast notifications for critical events (`IntrusionAlert`, `RestrictedEntityAlert`, `OccupancyThresholdEvent`).

REST & WebSocket API Reference
------------------------------

Streaming Endpoints
~~~~~~~~~~~~~~~~~~~

``GET /stream/{camera_id}``
   Yields live multipart MJPEG video stream: ``multipart/x-mixed-replace; boundary=frame``.

``WebSocket /ws/{camera_id}``
   Bidirectional WebSocket connection pushing real-time telemetry JSON packets:

   .. code-block:: json

      {
        "camera_id": "cam_01",
        "status": "online",
        "fps": 28.4,
        "resolution": "1280x720",
        "source_resolution": [1280, 720],
        "frame_count": 1420,
        "frame_seq": 1420,
        "inference_frame_seq": 1419,
        "inference_lag_ms": 18.5,
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
- ``GET /api/cameras/{camera_id}/telemetry``: Returns real-time bounding boxes, active tracks, zones, tripwires, resolution, and FPS for Cloud Hub canvas overlay proxying.
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
- ``POST /api/cameras/{camera_id}/record/start``: Start live MP4 recording for a camera stream via ``PipelineVideoWriter`` (prevents idle hibernation while recording).
- ``POST /api/cameras/{camera_id}/record/stop``: Stop and flush an active camera MP4 recording.
- ``GET /api/cameras/{camera_id}/record/status``: Retrieve active or finalized camera recording status and byte/frame counters.
- ``POST /api/cameras/{camera_id}/retry``: Re-probe an offline camera source (missing video file or disconnected USB device) and restart its ``StreamManager`` on demand without restarting the server.
- ``GET /api/system/models``: Inspect registered ONNX model weights presence and SHA-256 verification status.
- ``POST /api/system/models/verify``: Run SHA-256 integrity checks across registered ONNX model weights.
- ``POST /api/world/query``: Natural-language and structured semantic Q&A over FTS5 timelines, confidence state, and ``WorldGraph``.
- ``GET /api/world/confidence/{entity_id}``: Retrieve calibrated long-term confidence telemetry for an entity.
- ``GET /api/world/timeline``: BM25 full-text and structured search across indexed world timeline events.
- ``GET /api/world/snapshot``: Return full live ``WorldGraph`` topology and entity snapshot.
- ``GET /api/world/entities``: List active ``WorldEntity`` nodes with optional ``camera_id`` and ``min_confidence`` filters.

Modernized Responsive UI & Ergonomics (Milestone 10)
----------------------------------------------------

1. **Responsive Dialog Architecture & Scroll Containment**:
   All dialogs (Camera Manager, Universal Enrollment, Backup/Restore, Descriptor Versions, Review Reassign, Scenario Studio modals) follow strict viewport containment with ``max-height: min(88dvh, 800px)``, ``.modal-body-scroll`` with ``overscroll-behavior: contain``, and sticky footers with HTML5 ``form`` submission bindings.

2. **Stream Lifecycle & Standby Poster**:
   Stream detachment replaces active MJPEG streams with a standalone SVG standby poster (preventing broken image glyphs and infinite download loops), and reattaches seamlessly with cache-busting timestamps (``?t=${Date.now()}``).

3. **Bidirectional URL Hash Routing**:
   Direct deep-linking and browser navigation history support for all 9 core tabs (``#live``, ``#videos``, ``#gallery``, ``#timeline``, ``#analytics``, ``#alerts``, ``#studio``, ``#journey``, ``#review``) and modal subroutes (``#cameras``, ``#enroll``, ``#backup``, ``#versions``).

4. **Structured In-Page Modal Forms & Toast Notifications**:
   Eliminated blocking ``prompt()`` and sequential ``confirm()`` chains in Scenario Studio and Review & Learn, replacing them with dedicated modal forms for Zones, Directional Tripwires, Homography Calibration, Spatial Topology Transitions, and Quick-Enrollment. Replaced blocking ``alert()`` popups with non-intrusive toast notifications.

Diagnostic Trace Bridge & Crash Recording
-----------------------------------------

The dashboard incorporates the **Universal Runtime Diagnostic Trace Recorder** via ``dashboard.services.diagnostic_bridge``:

1. **Global Unhandled Panic Hook**:
   ``init_diagnostic_tracer()`` installs unhandled exception interceptors on process startup, capturing unexpected crashes and thread termination into ``.diagnostics/traces/`` and ``.diagnostics/trace_catalog.json``.
2. **FastAPI Exception Middleware**:
   ``DiagnosticTraceMiddleware`` catches unhandled HTTP 500 exceptions, logging contextual request metadata (``http_method``, ``http_path``, ``client_host``) and stack traces for automated root-cause analysis.
3. **Explicit Exception Logging**:
   ``capture_runtime_exception(exc, context)`` enables background tasks and streaming workers to record structured diagnostics without terminating the event loop.

Camera Pool Fault Tolerance & Hardware Staggering
-------------------------------------------------

The multi-camera pool (``dashboard.camera_pool.CameraPool``) provides fault-tolerant initialization:

1. **Graceful Offline Registration**:
   If a configured camera source path or stream is unreachable or missing, ``CameraPathResolver`` marks ``status: error``. The camera is registered offline in ``CameraHealthManager`` with error code ``FILE_NOT_FOUND`` rather than aborting the dashboard boot.
2. **DirectShow / MSMF Pin Lock Mitigation**:
   On Windows, rapid concurrent hardware camera acquisitions can cause driver deadlocks in Microsoft Media Foundation / DirectShow. Physical device acquisitions (integer or digit indices) are staggered by 150ms to ensure clean pin unbinding.

Scenario Combinations Matrix
----------------------------

.. list-table::
   :widths: 22 18 25 35
   :header-rows: 1

   * - Scenario / Objective
     - Mode / Inputs
     - Key Parameters
     - Exact Runnable Command
   * - Resilient Dev Dashboard
     - Bounded reload watcher
     - Watch source dirs only
     - ``python scripts/run_dashboard.py``
   * - Custom Port / Production
     - Headless / No reload
     - ``PORT=8080 RELOAD=false``
     - ``python scripts/run_dashboard.py``
   * - Interactive Local VMS
     - Web UI + synthetic stream
     - ``--source synthetic``
     - ``python main.py --source synthetic --port 8000``
   * - Standalone ASGI Server
     - FastAPI Uvicorn
     - ``--host 0.0.0.0 --port 8000``
     - ``python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000``
   * - Automated UI Regression
     - Headless TestClient
     - ``tests/test_dashboard_ui.py``
     - ``python -m unittest tests.test_dashboard_ui``
   * - Viewport Layout Audit
     - Headless CDP Chrome
     - ``--audit-layout --window-size 768x1024``
     - ``python scripts/cdp_inspect.py --url http://127.0.0.1:8000 --audit-layout --headless --window-size 768x1024``

Quickstart
----------

To launch the dashboard server with defensive reload boundaries and auto-configured ``PYTHONPATH``:

.. code-block:: bash

   # Recommended: Run with reload bounds (excludes database and log churn)
   python scripts/run_dashboard.py

   # Or specify host, port, and reload via environment variables:
   HOST=0.0.0.0 PORT=8000 RELOAD=true python scripts/run_dashboard.py

Alternatively, launch directly via Uvicorn:

.. code-block:: bash

   # Direct Uvicorn ASGI server
   python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000 --reload

Open your browser at ``http://127.0.0.1:8000``.

Data Reset & Clean Start (``scripts/reset_data.py``)
----------------------------------------------------

To wipe dashboard state cleanly before testing new features, use ``scripts/reset_data.py``.
It resolves paths in order of **CLI flag > environment variable > repository default**
(``TRACKER_DB_PATH`` / ``TRACKER_DB``, ``CAMERAS_CONFIG_PATH``, ``SCENARIOS_CONFIG_PATH``,
``TRACKER_CROPS_DIR``, ``TRACKER_REPORTS_DIR``, ``TRACKER_VIDEOS_DIR``, ``TRACKER_DEBUG_DIR``).

By default, ``reset_data.py``:

- Exports a pre-reset backup archive to ``data/backups/pre_reset_<timestamp>.zip`` via ``BackupManager`` (pass ``--no-backup`` to skip).
- Prompts per category: ``[Y/n]`` for ``db``, ``crops``, ``reports``, ``debug_session``, and ``docker_volumes``; ``[y/N]`` for ``videos`` and ``configs``.
- Refuses non-TTY/headless stdin unless ``--yes``, ``--prompt``, or ``--dry-run`` is passed, and aborts if port ``8000`` is active unless ``--force`` is set.

.. code-block:: bash

   # Preview what would be deleted without modifying files
   python scripts/reset_data.py --dry-run

   # Interactive per-category reset (works in headless shells with --prompt)
   python scripts/reset_data.py --prompt

   # Non-interactive local + Docker volume reset (docker compose down -v)
   python scripts/reset_data.py --target all --yes

   # Reset only a custom test DB and crops without creating a backup
   TRACKER_DB_PATH=data/test_clean.db python scripts/reset_data.py --only db,crops --yes --no-backup

Isolated Debug Mode & Error Inspector
-------------------------------------

Launch ``scripts/run_dashboard.py`` with ``--debug`` (or ``--clean-debug`` to wipe the previous
debug session before booting) to isolate all state under ``data/debug_session/``:

- **Isolated state**: ``tracker.db``, ``cameras.json``, ``scenarios.yaml``, ``crops/``, and ``reports/`` are redirected into ``data/debug_session/``.
- **Full diagnostics**: Enables ``DEBUG`` logging to rotating ``debug.log``, ``faulthandler.log`` for native C/C++ crashes, ``PYTHONASYNCIODEBUG=1``, ``FastAPI(debug=True)``, and ``events.jsonl`` structured ``WARNING+`` capture.

Use ``scripts/debug_inspect.py`` (or ``GET /api/system/debug/summary``) for a compact,
deduplicated Jenkins/Sentry-style summary of errors and tracebacks:

.. code-block:: bash

   # Boot a clean isolated debug session
   python scripts/run_dashboard.py --local --clean-debug

   # Inspect deduplicated warnings/errors/crashes
   python scripts/debug_inspect.py

   # Drill into issue #1 with full traceback and surrounding debug.log lines
   python scripts/debug_inspect.py --context 1

   # Emit compact JSON for CI or automated agents
   python scripts/debug_inspect.py --json

