# Intelligent Tracker — Modernization Milestone Plan

> **Vision:** Transform an 8-year-old legacy CCTV / Raspberry Pi object tracking project (Haar cascades, Python 2/3 mixed) into a modern, cross-platform Edge AI retail & security analytics platform with real-time zone counting, heatmaps, RTSP streaming, and instant alerting.
>
> **Working directory:** `g:\Mi unidad\projects\products\intelligent_tracker`
> **Active venv:** `.\.venv\` (Python 3.12.10 64-bit, Windows)
> **Test command:** `$env:MPLBACKEND="Agg"; .\.venv\Scripts\python.exe -m unittest discover tests`

---

## Status Overview

| Phase | Milestone | Status |
|---|---|---|
| 1 | Environment & Core Engine Revitalization | ✅ **COMPLETE** |
| 2 | Edge AI Detection (ONNX/YOLOv8/v11) | ✅ **COMPLETE** |
| 3 | RTSP Streams & Retail/Occupancy Analytics | ✅ **COMPLETE** |
| 4 | Object Identity Gallery, Re-ID & Sighting Database | ✅ **COMPLETE** |
| 5 | Event Dispatching & Alerting System | ✅ **COMPLETE** |
| 6 | Web Dashboard, Packaging & Edge Deployment | ✅ **COMPLETE** |
| 7 | Multi-Camera VMS, Auto-Discovery & Video Source Manager | ✅ **COMPLETE** |
| 8 | World Scenario Studio, Space Awareness & Homography BEV | ✅ **COMPLETE** |
| 9 | Artifact & Face Intelligence, Active Learning & Adaptive Memory | ✅ **COMPLETE** |
| 10 | VMS Dashboard Responsive Redesign, Ergonomics & Enterprise Hub Integration Readiness | ✅ **COMPLETE** |

---

## ✅ [Milestone 1] — Environment & Core Engine Revitalization
**Status: COMPLETE** — Verified: 21/21 tests pass in Python 3.12.10

### What was accomplished
- **Python 3.12 `.venv`** established (replaces legacy Conda Python 3.7 `InteligentTracker` env).
- **NumPy 2.x deprecation fixes** across `core.py`, `array_utils.py`, `detectors.py`, `geometry.py`:
  - `np.int` → `int`, `np.float` → `float`, `np.alltrue` → `np.all`
  - `collections.MutableMapping` → `collections.abc.MutableMapping`
- **Cross-platform compatibility** in `tests/test_core.py`:
  - Removed defunct `RRtoolbox` import
  - Unix `resource` module replaced with `psutil` cross-platform guard
  - Self-contained `TimeCode` context manager and `asizeof` helper
- **`detectors.py`**: Fixed `DETECTOR_PATH` to reliably find bundled cascade XML files
- **`forms.py`**: Graceful `MPLBACKEND` / Qt / Tk / Agg fallback chain
- **`periferials.py`**: Added `MockVideoCapture` for headless/no-camera testing
- **`tests/test_forms.py`**: Loop bound to prevent infinite block in headless test runs
- **`requirements.txt`**: Added `psutil>=5.8.0`
- **Rules adapted** (`rules/*.md`) for computer vision, RTSP security, GDPR privacy, edge deployment
- **`SETUP_GUIDE.md`**: Cross-platform setup guide (Windows, Linux/Raspberry Pi OS, macOS)
- **`TODO_MODERNIZATION.md`**: Full 5-phase roadmap
- **`MIGRATION_LOG.md`**: Persistent migration tracking initialized

### Verification
```powershell
$env:MPLBACKEND="Agg"
.\.venv\Scripts\python.exe -m unittest discover tests
# → Ran 21 tests in ~2s — OK
```

---

## ✅ [Milestone 2] — Edge AI Detection Architecture
**Status: COMPLETE** — Verified: 46/46 tests pass in Python 3.12.10

### What was accomplished
- **`BaseDetector` & `Detection` namedtuple**: Defined in `intelligent_tracker/detectors.py`, establishing a typed `(bbox, class_id, confidence, label)` interface.
- **`DetectorFactory`**: Flexible registry supporting `"haar"`, `"yolov8"`, `"yolo11"`, `"mock"`, `"color"`, `"face"`, `"eye"`, synced bidirectionally with `Detector.available_detectors`.
- **`OnnxDetector`**: Zero-dependency ONNX Runtime inference engine:
  - Pure NumPy letterbox resizing preserving aspect ratio with constant border padding.
  - Pure NumPy vectorized Non-Maximum Suppression (NMS) with multi-class offset.
  - Auto-selecting execution provider cascade: CUDA → DirectML (Windows) → OpenVINO (Intel) → CoreML (macOS) → CPU.
  - Coordinate remapping from letterbox back to original image space, strictly bounded.
  - Dynamic input dimension resolution and COCO 80 class labels / custom label dictionary.
  - Class filtering by ID or label name (`classes=[0]` or `classes=['person']`).
- **`HaarCascadeDetector`**: Concrete `BaseDetector` subclass wrapping OpenCV Haar cascade XML files. `FaceDetector` and `EyeDetector` adapted to subclass `HaarCascadeDetector`.
- **`ColorDetector`**: Enhanced to implement `BaseDetector.detect(frame)` returning `Detection` namedtuples.
- **`MockDetector`**: Deterministic synthetic bounding box generator for CI and headless testing.
- **Modernized OpenCV tracker support**: `Object.update_tracker` updated with `_get_cv2_tracker` helper to support OpenCV 4.x / 5.x tracker namespace relocation (`cv2` / `cv2.legacy`).
- **`scripts/download_models.py`**: Automated download utility with mirror failover, streaming progress, and SHA-256 integrity verification for `yolov8n.onnx` and `yolo11n.onnx`.
- **`main.py` CLI modernization**: Added `argparse` with `--detector`, `--source`, `--resolution`, `--framerate`, `--conf`, `--classes`, `--headless`, `--frames`.
- **`requirements.txt`**: Added `onnxruntime>=1.18.0`.
- **`tests/test_detectors.py`**: 25 comprehensive unit tests for interface contracts, mock generation, factory lookup, cascade fallback, letterbox preprocessing, NMS, and full ONNX inference.

### Verification
```powershell
# Download and verify models
.\.venv\Scripts\python.exe scripts/download_models.py --model yolov8n
.\.venv\Scripts\python.exe scripts/download_models.py --model yolo11n

# Run mock and ONNX detectors in headless mode
.\.venv\Scripts\python.exe main.py --detector mock --source synthetic --headless --frames 30
.\.venv\Scripts\python.exe main.py --detector yolov8 --source synthetic --headless --frames 30
.\.venv\Scripts\python.exe main.py --detector yolo11 --source synthetic --headless --frames 30

# Full test suite
$env:MPLBACKEND="Agg"
.\.venv\Scripts\python.exe -m unittest discover tests
# → Ran 46 tests in ~3.6s — OK (all pass)
```


---

## ✅ [Milestone 3] — RTSP Camera Streams & Retail / Occupancy Analytics (COMPLETE)
**Scope:** Robust multi-source video ingestion, zone definition, person counting, heatmaps.

### Deliverables Completed
- **`intelligent_tracker/video.py`**:
  - `VideoSource`: Non-blocking threaded video reader with bounded buffer queue, automatic frame-drop on lag (zero latency drift), auto-reconnect logic, and connection telemetry (`fps`, `drop_rate_pct`, `frames_read`, `frames_dropped`, `reconnections`).
  - `SyntheticFrameGenerator`: High-fidelity synthetic frame generator with moving targets crossing lines and dwelling in zones for automated testing without cameras.
- **`intelligent_tracker/geometry.py`**:
  - `Tripwire`: Bidirectional crossing detection using centroid trajectory and vector normal analysis, counters (`total_in`, `total_out`), and visualization drawing.
  - `ZoneROI`: Polygonal region of interest using `cv2.pointPolygonTest` with occupant state machine, entry/exit/dwell events, dwell time estimation, and translucent overlay rendering.
  - `ZoneEvent` & `TripwireEvent`: Strongly typed dataclasses with dictionary serialization.
  - `Area` & `Line` in `intelligent_tracker/high_objects.py`: Integrated to wrap `ZoneROI` and `Tripwire`.
- **`intelligent_tracker/tracker.py`**:
  - `Track`: Rich tracked entity representation with centroid history, velocity estimation, dwell times, and state lifecycle (`tentative`, `confirmed`, `lost`).
  - `CentroidTracker`: Two-stage IoU and Euclidean distance association with zero heavy dependencies.
  - `SortTracker`: Simple Online and Realtime Tracking using 2D kinematic Kalman filters in pure NumPy.
  - `TrackerFactory`: Dynamic registration and instantiation.
- **`intelligent_tracker/analytics.py`**:
  - `OccupancyHeatmap`: 2D spatial Gaussian density accumulation, continuous temporal decay, false-color overlay blending (JET/INFERNO), PNG snapshot, and CSV grid exports.
  - `AnalyticsEngine`: Central coordinator managing multi-zone occupancy, tripwire tallies, events, and telemetry report generation.
- **Declarative YAML Configurations & CLI (`main.py`)**:
  - `configs/demo.yaml`: Synthetic demo configuration.
  - `configs/retail.yaml`: Production-ready retail analytics configuration.
  - `--config`, `--tracker`, `--heatmap`, `--output` video recording integration in `main.py`.
- **`requirements.txt`**: Added `pyyaml>=6.0.0`.
- **Documentation**:
  - `documentation/analytics.rst`: Comprehensive technical documentation.
  - `documentation/index.rst`: Added `analytics` to Sphinx toctree.
  - `README.rst`: Updated capabilities, CLI options table, test commands, and roadmap.
- **Unit Test Suite**:
  - `tests/test_video.py`: 5 tests covering VideoSource, synthetic generation, metrics, and frame drops.
  - `tests/test_tracker.py`: 7 tests covering Track, IoU matching, CentroidTracker lifecycle, and SortTracker.
  - `tests/test_analytics.py`: 5 tests covering Tripwire, ZoneROI, OccupancyHeatmap, and AnalyticsEngine.
  - Full suite: **63 tests passing (100% green)**.

### Verification
```powershell
# Synthetic demo with YAML configuration in headless mode
.\.venv\Scripts\python.exe main.py --config configs/demo.yaml --headless --frames 30

# YOLOv8 with YAML configuration and video recording export
.\.venv\Scripts\python.exe main.py --config configs/demo.yaml --detector yolov8 --headless --frames 30 --output scratch/test_output.mp4

# Full test suite (63 tests)
$env:MPLBACKEND="Agg"
.\.venv\Scripts\python.exe -m unittest discover tests
# → Ran 63 tests in ~4.3s — OK (all pass)
```


---

## ✅ [Milestone 4] — Object Identity Gallery, Re-Identification (Re-ID) & Sighting Database
**Status: COMPLETE** — Verified: 97/97 tests pass in Python 3.12.10
**Scope:** Persistent SQLite entity database, visual Re-ID embeddings (ONNX + color descriptor fallback), interactive screen selection/tagging, cross-session re-appearance matching, offline recording occurrence analytics, predictive dead-reckoning trajectory coasting, and automatic session gallery re-identification.

### Objectives & Deliverables Completed (4a–4f)

**4a — Persistent SQLite Entity & Sighting Database (`intelligent_tracker/database.py`):**
- Embedded, zero-configuration local database (`data/tracker.db`), edge-ready for Raspberry Pi, PC, and servers.
- `TrackerDB` thread-safe manager:
  - `entities` table: `(id INTEGER PRIMARY KEY, name TEXT, category TEXT, status TEXT, notes TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)`
    - Categorization: e.g. `"person"`, `"vehicle"`, `"vip"`, `"employee"`, `"customer"`, `"delivery"`, `"restricted"`, or custom tags.
  - `entity_signatures` table: `(id INTEGER PRIMARY KEY, entity_id INTEGER, embedding BLOB, crop_path TEXT, created_at TIMESTAMP)`
    - Stores multi-dimensional feature vector representations and representative thumbnail crops.
  - `sightings` table: `(id INTEGER PRIMARY KEY, entity_id INTEGER, track_id INTEGER, source TEXT, timestamp TIMESTAMP, zone_id TEXT, bbox TEXT, confidence REAL, snapshot_path TEXT)`
    - Complete audit trail of where and when each entity was seen.
  - Indexed queries for rapid lookup: `(entity_id, timestamp)` and `(source, timestamp)`.

**4b — Visual Feature Descriptors & Re-ID Embeddings (`intelligent_tracker/reid.py`):**
- Abstract `BaseFeatureExtractor` interface: `extract(frame, bbox) -> np.ndarray` (L2-normalized feature vector).
- Implementations:
  - **`OnnxReIDExtractor`**: Lightweight ONNX Re-ID model (`osnet_x0_25.onnx` ~907 KB, 512-d embeddings). Runs via ONNX Runtime with multi-platform execution provider cascade (CUDA/DirectML/OpenVINO/CPU). Accommodates both dynamic and fixed batch architectures.
  - **`ColorHistogramExtractor`**: Ultra-lightweight CPU fallback using spatial-grid joint 3D HSV color histograms (zero neural network dependency, pure NumPy/OpenCV, sub-millisecond execution on Raspberry Pi). Re-connects directly to the original project's descriptor vision (`self.descriptors`).
- Cosine similarity matching: vectorized `batch_cosine_similarity(gallery_matrix, query_vector)`.

**4c — Screen Selection, Interactive Tagging & GUI Controls (`intelligent_tracker/interactive.py`):**
- **Interactive Screen Selection & Inspection**:
  - Mouse click on any tracked bounding box in the GUI / display window to select and inspect the target.
  - Real-time inspector overlay displaying track ID, classification confidence, trajectory, dwell duration, and speed.
- **Entity Enrollment Dialog**:
  - Interactive prompt / dialog: assign name (e.g. `"Forklift #02"`, `"Alice"`, `"White Sedan ABC-123"`), assign category/tags (`"Staff"`, `"VIP"`, `"Authorized"`), add notes.
  - Instantly enrolls entity, thumbnail crop, and feature embedding vector into the SQLite gallery.
- **Interactive Control Bar & Video Navigation**:
  - On-screen / HUD controls: Play, Pause (Spacebar), Step frame-by-frame, Clear tracks (`d`), Heatmap toggle (`h`), and Snapshot export (`s`), Enroll entity (`e`).
  - Interactive ROI drawing: mouse drag-and-drop to define new virtual tripwires (`t`) or zone polygons (`z`) directly on the live video window.
  - Dual GUI support: High-performance OpenCV HUD (`--gui opencv`) and Classical Matplotlib navigation toolbar (`--gui forms`).
- **Python API**:
  - `db.enroll_entity(name, category, frame, bbox, notes)` for headless scripts, REST APIs, or dashboard integration.
  - Ability to re-assign or merge tracks if user corrects an identification.

**4d — Gallery Matcher & Re-Appearance Engine (`intelligent_tracker/matcher.py`):**
- Combines short-term frame-to-frame tracking (`CentroidTracker`) with long-term gallery Re-ID:
  - As an object is tracked, collect and average embeddings across high-confidence frames with temporal feature smoothing.
  - Query `TrackerDB` gallery: if top cosine similarity exceeds `reid_threshold` (e.g. ≥ 0.65), automatically link the track to the enrolled `entity_id`.
  - When an object leaves the camera view and reappears later (minutes, days, or across different camera sources), the system recognizes the entity and displays identification badge.
  - Emits `EntityIdentifiedEvent` and records debounced sighting in `sightings` table.

**4e — Offline Video Recording Indexer & Occurrence Analytics (`intelligent_tracker/batch.py`):**
- Batch process recorded video files (`.mp4`, `.avi`, `.mkv`):
  - Ingests video at fast-forward speed or sampled frame rate (`--sample-rate N`).
  - Detects, tracks, extracts features, and catalogs all occurrences in the database.
- Occurrence queries & analytics:
  - **Sighting Timeline**: "List all timestamps and video files where Entity X appeared."
  - **Visit Frequency & Dwell Time**: Total duration observed, visit count, first seen, last seen.
  - **Zone Journey**: Flow of the entity across defined zones and tripwires.
**4f — Predictive Motion Coasting, Dead-Reckoning & Automatic Session Re-ID:**
- **Velocity-based Trajectory Coasting**: Extrapolates bounding box position during brief detector dropouts using smoothed physical velocity ($\vec{p}_{t} = \vec{p}_{t-1} + \vec{v} \cdot \Delta t$) for up to `coast_frames` (default: 30–45 frames / 1.0–1.5s).
- **Track Lifecycle States**: Explicitly tracks `active` / `confirmed`, `predicting` / `coasting`, and `dormant` states.
- **Zone & Occupancy Continuity**: Keeps zone presence and dwell time counter alive during predictive coasting, preventing spurious entry/exit event oscillation.
- **Predictive Rendering Style**: Distinct dashed/dimmed bounding box with `[PREDICTING]` badge in OpenCV HUD overlay.
- **Automatic Session Gallery**: Automatically registers and maintains stable canonical identities (`Person #1`, `Person #2`, etc.) in an in-memory session gallery.
- **Fused Affinity Re-Linker**: Matches re-appearing objects using visual Re-ID cosine similarity combined with a spatial proximity boost if entering near the boundary/location where the object was last seen leaving.
- **Unified Persistent HUD Labels**: Displays stable session identity labels throughout the video, avoiding track ID inflation (e.g. preventing the same person from becoming Person #35).

### Verification & Test Suite
- Full test suite: **97 tests passing (100% green)** in ~4.9s.
- Verified commands:
```powershell
# 1. Run full test suite (97 tests)
$env:MPLBACKEND="Agg"
.\.venv\Scripts\python.exe -m unittest discover tests

# 2. Interactive tagging studio CLI help & standalone app
.\.venv\Scripts\python.exe -m intelligent_tracker.interactive --help

# 3. Live tracking with YOLOv8, ONNX Re-ID, and SQLite database
.\.venv\Scripts\python.exe main.py --config configs/demo.yaml --detector yolov8 --reid onnx --db data/tracker.db --headless --frames 30

# 4. Offline video recording indexer and occurrence analytics report
.\.venv\Scripts\python.exe -m intelligent_tracker.batch --video scratch/test_output.mp4 --db data/tracker.db --report
```

---

## ✅ [Milestone 5] — Event Dispatching & Alerting System (COMPLETE)
**Scope:** Webhook, Telegram, and MQTT alerting on zone events, tripwires, and tagged entity recognition.

### Objectives Completed

**5a — Event Bus:**
- `intelligent_tracker/events.py`
  - `EventBus`: Thread-safe publish/subscribe broker with async worker threads and background queue.
  - Zero event loss with synchronous (`sync=True`) and asynchronous (`sync=False`) delivery.
  - Type-based (`event_type=...`), predicate-based (`filter_fn=...`), and universal subscriber registration.
  - Ring buffer history query (`get_recent_events`).
  - Error isolation: Handlers execute with exception boundaries preventing worker thread crashes.
  - Typed dataclasses: `BaseEvent`, `ZoneEvent`, `TripwireCrossEvent`, `IntrusionAlert`, `OccupancyThresholdEvent`, `EntityIdentifiedEvent`, `RestrictedEntityAlert`.
  - Base64 JPEG frame and bounding box crop encoders: `frame_to_base64()`, `crop_to_base64()`, `decode_snapshot_base64()`.

**5b — Webhook Dispatcher:**
- `WebhookDispatcher`: HTTP POST JSON delivery with exponential backoff retries (3 retries).
- Configurable URL, Bearer/custom auth headers, timeout, and event type filtering.
- Payload includes `camera_id`, `zone_id`, `entity_id`, `entity_name`, `event_type`, `timestamp`, `data`, and optional JPEG `snapshot`.
- Telemetry metrics: `sent_count`, `failed_count`, `retry_count`, `last_status_code`.

**5c — Telegram Bot:**
- `TelegramDispatcher`: Telegram Bot API notifications with visual Markdown formatting and status emojis.
- Multipart photo upload attachment (`sendPhoto`) with base64 JPEG decode fallback.
- Rate-limiting cooldown (default 60s per zone/entity) to eliminate notification fatigue.
- Interactive `/status`, `/occupancy`, and `/help` command responder.
- Offline mock mode for headless CI and local automated testing.

**5d — MQTT Publisher:**
- `MqttPublisher`: Paho MQTT (compatible with 2.x `CallbackAPIVersion.VERSION2` and 1.x).
- Telemetry topics: `tracker/{camera_id}/occupancy` (JSON, retained=True).
- Event stream: `tracker/{camera_id}/events` (JSON, retained=False).
- Sighting topic: `tracker/{camera_id}/sightings/{entity_id}` (JSON, retained=True for last known location).
- Last Will & Testament (LWT) topic: `tracker/system/status` (`"online"` / `"offline"`).

**5e — Configurable Rules & Entity Filters:**
- `QuietHours`: Time-of-day schedule evaluation supporting overnight spans crossing midnight (e.g. 22:00 to 06:00) and day-of-week filters.
- `AlertRule`: Rule matching on zone, event type, entity category (e.g. `restricted`, `unknown`), minimum dwell time, and quiet hours.
- `AlertRuleEngine`: Evaluates incoming events, checks rule cooldowns, captures visual snapshots, and publishes derived `IntrusionAlert` or `RestrictedEntityAlert` events.
- `setup_event_pipeline()`: Declarative pipeline setup from YAML configuration (`configs/alert_demo.yaml`).

### Verification & Test Suite
- Full test suite: **115 tests passing (100% green)** in ~5.8s.
- Milestone 5 dedicated test suite: **18 tests passing** in ~1.2s.
- Verified commands:
```powershell
# 1. Run full test suite (115 tests)
$env:MPLBACKEND="Agg"
.\.venv\Scripts\python.exe -m unittest discover tests

# 2. Webhook, Telegram, MQTT, and Rules unit test suite (18 tests)
.\.venv\Scripts\python.exe -m tests.test_events

# 3. Live tracking with alerting pipeline (Webhooks, Telegram, MQTT, Rules)
.\.venv\Scripts\python.exe main.py --config configs/alert_demo.yaml --headless --frames 30
```

---

## ✅ [Milestone 6] — Web Dashboard, Packaging & Edge Deployment (COMPLETE)
**Scope:** Modern live web dashboard with entity gallery and sighting search, Docker containers, systemd service, Sphinx docs.

### Objectives

**6a — FastAPI + WebSocket Dashboard:**
- `dashboard/` directory — FastAPI app
  - Live MJPEG stream endpoint: `GET /stream/{camera_id}`
  - WebSocket metrics endpoint: `WS /ws/{camera_id}` — pushes occupancy and sighting JSON in real time.
  - REST API: `GET /cameras`, `GET /zones`, `GET /analytics/heatmap`, `GET /entities`, `GET /sightings`, `GET /events`, `POST /tag`, `GET /status`.
- HTML5/Canvas + CSS + Chart.js frontend:
  - Live annotated camera feed with interactive click-to-tag bounding box capability in browser.
  - **Entity Gallery View**: Grid of enrolled people/objects, category badges, appearance counts.
  - **Sighting Timeline Player**: Search sightings by entity name, date/time range, or zone.
  - Zone occupancy counters and entry/exit time series charts.
  - Heatmap overlay toggle and alert history log.

**6b — Raspberry Pi & Edge Deployment:**
- `Dockerfile.arm64` + `Dockerfile.amd64` + `Dockerfile` (multi-stage: builder + slim runtime).
- `docker-compose.yml`: `tracker` service + `dashboard` service + `mosquitto` MQTT broker.
- `deployment/intelligent-tracker.service` and `deployment/intelligent-tracker-dashboard.service` — systemd units for Raspberry Pi OS / Ubuntu.
- Hardware acceleration flags:
  - Coral Edge TPU delegate (`EdgeTpuDetector` with `libedgetpu.so.1` / `tflite_runtime`) for RPi.
  - `libcamera` GStreamer pipeline support for Raspberry Pi Camera Module v2/v3/HQ.
  - Intel NUC: OpenVINO execution provider hooks.

**6c — CI/CD:**
- `.github/workflows/ci.yml`: Python 3.10, 3.11, 3.12 matrix, ruff lint, unit test suite, and Sphinx docs build.
- Badge on `README.rst`.

**6d — Sphinx Documentation Modernization:**
- Modern Sphinx 9+ configuration (`conf.py`) with `sphinx_rtd_theme`.
- Auto-generate API reference for all modules including `dashboard.rst` and `deployment.rst`.
- Clean system architecture diagram in `index.rst`.
- Verified build with zero warnings (`sphinx -W --keep-going`).

**6e — `install_opencv.sh` update:**
- Modernized for Raspberry Pi OS Bookworm (64-bit / Debian 12) and Ubuntu 24.04 LTS (`--apt`, `--pip`, `--source`).

### Verification & Test Suite
- Full test suite: **125 tests passing (100% green)** in ~6.0s.
- Milestone 6 dedicated test suite: **10 tests passing** in ~0.57s (`tests/test_dashboard.py`).
- Sphinx documentation build: **Passed with 0 warnings** (`sphinx -W documentation/ documentation/_build/html/`).
- Verified commands:
```powershell
# 1. Run complete unit test suite (125 tests)
$env:MPLBACKEND="Agg"
.\.venv\Scripts\python.exe -m unittest discover tests

# 2. Web Dashboard dedicated unit test suite (10 tests)
.\.venv\Scripts\python.exe -m unittest tests/test_dashboard.py

# 3. Build Sphinx documentation without warnings
.\.venv\Scripts\python.exe -m sphinx -W --keep-going documentation/ documentation/_build/html/

# 4. Start local Web Dashboard server
.\.venv\Scripts\python.exe -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
```

---

## ✅ [Milestone 7] — Multi-Camera VMS, Auto-Discovery & Video Source Manager (COMPLETE)
**Status: COMPLETE** — Verified: 156/156 tests pass in Python 3.12.10
**Scope:** Multi-Camera VMS, hardware USB & ONVIF network auto-discovery, vendor RTSP credential builders (Hikvision, Tapo, EZVIZ, Dahua, Generic), dynamic multi-stream pool (CameraPool) without server restarts, multi-grid switcher (1x1, 2x2, 3x3), local video file upload with timeline scrubber (1x, 2x, 4x, 8x), automatic boot restoration, and full portable system state snapshot export/import (.zip).

### Objectives & Deliverables Completed (7a–7f)

**7a — Dual Camera Auto-Discovery (`intelligent_tracker/discovery.py`):**
- **Physical USB Webcams**: Cross-platform video capture probing across physical indices using DirectShow (`cv2.CAP_DSHOW` on Windows) and V4L2/Default on Linux.
- **ONVIF WS-Discovery**: Broadcasts standard XML SOAP probe messages over UDP port 3702 to `239.255.255.250`. Detects Network Video Transmitters (NVTs) and parses XAddrs.
- **LAN Subnet RTSP Scanner**: High-speed concurrent socket scanning across ports 554, 8554, and 8000.
- **Diagnostics & Preview**: `test_camera_connection()` with fast pre-connection socket reachability checks, decoded resolution, FPS, and base64 JPEG snapshot for live browser preview.

**7b — Vendor RTSP Presets & URL Credential Builder:**
- Built-in vendor presets with URL-encoded credential builder (`urllib.parse.quote`):
  - **Hikvision**: `rtsp://{user}:{pass}@{ip}:554/Streaming/Channels/{channel}01` (main) or `02` (sub)
  - **TP-Link Tapo**: `rtsp://{user}:{pass}@{ip}:554/stream1` (HD) or `/stream2` (SD)
  - **EZVIZ**: `rtsp://admin:{verification_code}@{ip}:554/h264/ch{channel}/main`
  - **Dahua / Imou**: `rtsp://{user}:{pass}@{ip}:554/cam/realmonitor?channel={channel}&subtype=0`
  - **Generic RTSP / NVR Channel**: Custom user-defined string.

**7c — Dynamic Multi-Stream Orchestrator (`dashboard/camera_pool.py`):**
- Manages concurrent `StreamManager` pipelines in background threads.
- Hot-add (`add_camera`), edit (`update_camera`), toggle (`toggle_camera`), and remove (`remove_camera`) camera feeds dynamically without restarting the FastAPI server.
- Automatic boot restoration: Restores all configured cameras from `configs/cameras.json`.

**7d — Local Video File Upload & Playback Scrubber:**
- Upload `.mp4`, `.avi`, `.mkv`, `.mov` recordings into `data/videos/` via drag-and-drop or `POST /api/videos/upload`.
- In-browser playback scrubber (`dashboard/static/video_scrubber.js`) with frame stepping (`< -1 Frame`, `> +1 Frame`), and variable playback rates (1x, 2x, 4x, 8x).
- One-click registration of video recordings as active live camera feeds.
- Offline occurrence indexer via `BatchVideoIndexer` returning entity counts and sighting audit records.

**7e — Responsive Multi-Camera Grid Switcher:**
- Interactive grid mode switcher in web dashboard:
  - **1x1 Focused View**: High-resolution single camera stream with real-time bounding box canvas and click-to-tag.
  - **2x2 Quad View**: 4-camera grid with status indicators, FPS badges, and track counters.
  - **3x3 Matrix View**: 9-camera operational matrix. Clicking any tile instantly switches to focused 1x1 view.

**7f — State Persistence, Auto-Restore & Full Import/Export (`intelligent_tracker/backup.py`):**
- **Automatic Boot Restoration**: Restores configured cameras, zones, and rules on launch.
- **One-Click System Snapshot Export (`GET /api/backup/export`)**: Packages SQLite database (`tracker.db`), signature crops (`data/crops/`), and configurations (`configs/`) into a versioned `.zip` archive with SHA-256 checksums.
- **Full System Migration (`POST /api/backup/import`)**: Restores database, crops, and configurations with Zip-Slip path traversal protection.
- **CLI Tooling**: `python -m intelligent_tracker.backup --export backup.zip`, `--import backup.zip`, and `--info backup.zip`.

### Verification & Test Suite
- Full test suite: **156 tests passing (100% green)** in ~15.6s.
- Milestone 7 dedicated test suites:
  - `tests/test_discovery.py`: **11 tests passing** in ~0.43s.
  - `tests/test_camera_pool.py`: **8 tests passing** in ~3.29s.
  - `tests/test_backup.py`: **6 tests passing** in ~0.69s.
  - `tests/test_vms_api.py`: **6 tests passing** in ~3.55s.
- Sphinx documentation build: **Passed with 0 warnings** (`sphinx -W --keep-going documentation/ documentation/_build/html/`).
- Verified commands:
```powershell
# 1. Run complete unit test suite (156 tests)
powershell -Command "$env:MPLBACKEND=\"Agg\"; .\.venv\Scripts\python.exe -m unittest discover tests"

# 2. Run Milestone 7 dedicated test suites (31 tests)
.\.venv\Scripts\python.exe -m unittest tests/test_discovery.py
.\.venv\Scripts\python.exe -m unittest tests/test_camera_pool.py
.\.venv\Scripts\python.exe -m unittest tests/test_backup.py
.\.venv\Scripts\python.exe -m unittest tests/test_vms_api.py

# 3. CLI backup export and inspection
.\.venv\Scripts\python.exe -m intelligent_tracker.backup --export backup.zip
.\.venv\Scripts\python.exe -m intelligent_tracker.backup --info backup.zip

# 4. Build Sphinx documentation without warnings
.\.venv\Scripts\python.exe -m sphinx -W --keep-going documentation/ documentation/_build/html/
```

---

## ✅ [Milestone 8] — World Scenario Studio, Space Awareness & Ground Plane Homography
**Status: COMPLETE** — Verified: 187/187 tests pass in Python 3.12.10

### What was accomplished

**8a — Interactive In-Browser Scenario Studio (`dashboard/static/studio.js`):**
- **Polygonal Zone Drawing**: Interactive vertex placement, rubberband lines, closure checks, dwell thresholds, capacity limits, category filters, and color pickers.
- **Directional Tripwire Drawing**: Two-point line segments with orthogonal normal vectors (IN/OUT directional arrows), bidirectional toggling, and line crossing counters.
- **Real-Time Hot Injection**: Synchronizes live scenario changes directly into active `StreamManager.analytics` pipelines without restarting streams or interrupting tracking.

**8b — 4-Point Ground Plane Homography & 2D BEV Minimap (`intelligent_tracker/homography.py`):**
- **Perspective Matrix Calibration**: 4-point perspective transform (`cv2.getPerspectiveTransform`) and pseudoinverse/analytical inversion mapping camera image coordinates $\leftrightarrow$ metric ground plane $(X, Y)$ in meters.
- **Bottom-Center Contact Mapping**: Tracks mapped to ground plane via contact coordinate $(x + w/2, y + h)$.
- **Tactical Bird's-Eye-View (BEV) Minimap**: Dark slate-themed 2D top-down minimap canvas rendering metric distance grids, transformed zone polygons, track markers, velocity vectors, and entity names.
- **Picture-in-Picture (PiP) Stream & Image Endpoint**: Live minimap rendered in MJPEG stream PiP overlay and served via `GET /api/scenarios/bev/{camera_id}`.

**8c — Cross-Camera Topological Space Awareness (`intelligent_tracker/topology.py`):**
- **Domain Realization**: Concrete realization of `Scene`, `Area`, and `Line` abstractions from `intelligent_tracker.high_objects`.
- **Spatial Transition Links**: Physical pathways between camera zones (`SpatialTransitionLink`) with configurable transit windows $[T_{min}, T_{max}]$, prior boosting score bonus, and bidirectional link mirroring.
- **Predictive Spatial Priors (`ActiveSpatialPrior`)**: Zone exit events automatically spawn live predictive priors with transit window filtering.
- **Bayesian Re-ID Prior Boosting (`intelligent_tracker/matcher.py`)**: Boosts candidate Re-ID similarity ($S_{final} = \min(1.0, S_{vis} + \text{prior\_boost})$) when appearing in target camera zones within predicted transit windows, eliminating identity swapping across cameras.

**8d — Trajectory Journey Search & Video Exporter (`intelligent_tracker/journey.py`):**
- **Multi-Camera Hop Segmentation**: Aggregates sightings from `TrackerDB` into discrete camera hops with dwell durations and transit delays between successive cameras.
- **Narrative Synthesis**: Automatically formats human-readable journey descriptions (e.g. `10:02 CAM_01 (Door Exit) [10s] -> 10:04 CAM_02 (Door Entrance) [15s]`).
- **One-Click MP4 Journey Video Export**: Slices recorded camera clips or synthesizes an animated tactical video summary with camera badges, timestamps, and bounding box highlights into a downloadable MP4 file (`POST /api/journey/export`).

**8e — Floating Overlay Control Toolbar (`dashboard/static/index.html`, `dashboard/static/app.js`):**
- Floating overlay controls on live monitor to independently toggle bounding boxes (`bboxes`), track IDs (`track_ids`), dwell timers (`dwell_timers`), velocity vectors (`velocity`), zones (`zones`), tripwires (`tripwires`), heatmap (`heatmap`), BEV minimap (`bev_minimap`), and HUD status bar (`hud_bar`).
- REST endpoints `GET /api/cameras/{id}/overlays` and `POST /api/cameras/{id}/overlays` with client synchronization.

**8f — Dual Persistence & Declarative Scenarios (`intelligent_tracker/scenarios.py`):**
- Declarative YAML persistence in `configs/scenarios.yaml`.
- Relational SQLite tables in `intelligent_tracker/database.py` (`spatial_zones`, `spatial_tripwires`, `spatial_transitions`, `homography_calibrations`).
- High-level `ScenarioManager` orchestrating memory, SQLite, YAML, and active pipelines.

### Verification & Test Suite
- Full test suite: **187 tests passing (100% green)** in ~19.7s.
- Milestone 8 dedicated test suites (31 new tests):
  - `tests/test_homography.py`: **7 tests passing** (calibration, forward/inverse mapping, bottom-center contact point, polygon projection, BEV minimap, serialization).
  - `tests/test_topology.py`: **8 tests passing** (bidirectional links, zone exit triggers, transit windows, expiration, weighted similarity boost, prior consumption, matcher integration).
  - `tests/test_scenarios.py`: **5 tests passing** (zone/tripwire/homography CRUD, SQLite & YAML persistence, startup reload).
  - `tests/test_journey.py`: **3 tests passing** (multi-camera journey reconstruction, transit delay calculation, MP4 video synthesis).
  - `tests/test_scenario_api.py`: **7 tests passing** (FastAPI REST endpoints for scenarios, zones, tripwires, homography, BEV minimap, topology, journey search/export, overlay controls).
- Sphinx documentation build: **Passed with 0 warnings** (`sphinx -W --keep-going documentation/ documentation/_build/html/`).
- Verified commands:
```powershell
# 1. Run complete unit test suite (187 tests)
$env:MPLBACKEND='Agg'; .\.venv\Scripts\python.exe -m unittest discover tests

# 2. Run Milestone 8 dedicated test suites (31 tests)
.\.venv\Scripts\python.exe -m unittest tests/test_homography.py
.\.venv\Scripts\python.exe -m unittest tests/test_topology.py
.\.venv\Scripts\python.exe -m unittest tests/test_scenarios.py
.\.venv\Scripts\python.exe -m unittest tests/test_journey.py
.\.venv\Scripts\python.exe -m unittest tests/test_scenario_api.py

# 3. Build Sphinx documentation without warnings
.\.venv\Scripts\python.exe -m sphinx -W --keep-going documentation/ documentation/_build/html/
```

---

## ✅ [Milestone 9] — Artifact & Face Intelligence, Active Learning & Adaptive Memory (COMPLETE)
**Status: COMPLETE** — Verified: 209/209 tests passing (100% green across all unit and integration tests)

### What was accomplished

**9a — Universal Artifact & Face Enrollment (`intelligent_tracker/enrollment.py`, `intelligent_tracker/detectors.py`, `intelligent_tracker/reid.py`):**
- **YuNet Face Detector (`YuNetFaceDetector`)**: Integrated OpenCV Zoo's lightweight YuNet ONNX face detection model (`models/face_detection_yunet_2023mar.onnx`) supporting micro-face localization. Registered with `DetectorFactory`.
- **Dual-Model Feature Extractor (`DualModelFeatureExtractor`)**: Fuses artifact/body deep Re-ID appearance vectors with localized facial biometric embeddings, maintaining strict L2 normalization. Registered with `ReIDExtractorFactory`.
- **Universal Enrollment Manager (`UniversalEnrollmentManager`)**: Universal enrollment for any real-world entity (humans, vehicles, delivery vans, guard dogs, domestic pets, tools, packages) via freeze-frame crop, base64 payload, or frame + bbox.
- **Initial Locked Anchor Snapshot**: Automatically marks ground-truth enrollment crops as immutable Locked Anchors and records initial descriptor version 1 in SQLite database.

**9b — Role-Based Spatial Access Control (RSAC) & Pet Whitelisting (`intelligent_tracker/rsac.py`, `intelligent_tracker/analytics.py`):**
- **Custom Semantic Categories**: Dynamic categories with customizable color badges (`person`, `family_car`, `delivery_truck`, `cleaning_crew`, `guard_dog`, `pet`, `vip`, `restricted`).
- **Zone Permission Matrix**: Evaluation of allowed and denied categories per zone with schedule evaluation (24/7 wildcard, weekday business hours, etc.).
- **Entity Overrides**: Specific entity-level access grants or denials overriding general category rules.
- **Pet Alarm Suppression**: Perimeter tripwires and intrusion zones automatically suppress breach alarms for whitelisted domestic pet categories or labels, routing informational `PetActivityEvent` alerts instead of critical breach alarms.

**9c — Human-in-the-Loop Active Learning ("Review & Learn" Inbox) (`intelligent_tracker/active_learning.py`):**
- **Ambiguous Candidate Triage**: Detections with similarity in the uncertainty band $[0.45, 0.70)$ are intercepted, debounced, cropped, and saved to `data/crops/review_*.jpg`.
- **Event Bus Dispatching**: Emits `ReviewItemQueuedEvent` over WebSocket channels to live dashboard operators.
- **Operator 1-Click Triage Actions**:
  - `confirm_candidate`: Confirms match as ground truth and enrolls candidate crop as a **Locked Anchor**.
  - `reassign_candidate`: Reassigns candidate crop to a different chosen entity as a Locked Anchor.
  - `enroll_as_new`: Registers candidate crop as a newly created entity with initial version 1 snapshot.
  - `dismiss_candidate`: Rejects candidate without altering gallery or models.

**9d — Locked Anchors, Bounded EMA Updates & Versioned Memory Rollback (`intelligent_tracker/tracker.py`, `intelligent_tracker/matcher.py`, `intelligent_tracker/database.py`):**
- **Track Occlusion Reasoning (`check_track_occlusions`)**: Pairwise track IoU checks flag overlapping tracks ($\text{IoU} > 0.3$) with `is_cluttered = True`. Re-ID feature accumulation is frozen during clutter to prevent identity swaps.
- **Bounded EMA Adaptation**: Running descriptor centroids are updated continuously via Exponential Moving Average ($\alpha = 0.05$) only when observation similarity and resulting smoothed centroid remain bounded against ground-truth Locked Anchors ($\cos(\mathbf{c}, \mathbf{a}) \ge 0.65$).
- **Descriptor Version History & Rollback**: Complete snapshot history in SQLite `descriptor_versions`. 1-click rollback via `db.rollback_descriptor` and REST API.

**9e — REST API & Glassmorphism Dashboard UI (`dashboard/app.py`, `dashboard/static/`):**
- **REST API Endpoints**:
  - `GET /api/cameras/{id}/freeze_frame`
  - `POST /api/enroll`
  - `GET /api/active-learning/queue` & `GET /api/active-learning/{id}`
  - `POST /api/active-learning/{id}/confirm`, `reassign`, `enroll-new`, `dismiss`
  - `GET /api/rsac/categories`, `POST /api/rsac/categories`, `DELETE /api/rsac/categories/{id}`
  - `GET /api/rsac/rules`, `POST /api/rsac/rules`, `DELETE /api/rsac/rules`
  - `GET /api/pets/whitelist`, `POST /api/pets/whitelist`, `DELETE /api/pets/whitelist/{label}`
  - `GET /api/entities/{id}/versions`
  - `POST /api/entities/{id}/rollback/{version}`
- **Web UI (`dashboard/static/index.html`, `review_and_rsac.js`, `styles.css`)**:
  - Review & Learn triage inbox tab with confidence meters and thumbnail comparison cards.
  - Interactive freeze-frame canvas bounding box selection modal with category badge picker.
  - Version History & Rollback modal with chronological snapshot timeline.
  - Category badge pill styles and live toast notification prompts.

### Verification & Test Suite
- Full test suite: **209 tests passing (100% green)** across all unit and integration tests.
- Milestone 9 dedicated test suites (22 new tests):
  - `tests/test_rsac.py`: **6 tests passing** (categories, schedule active checks, allow/deny rules, entity overrides, pet suppression).
  - `tests/test_active_learning.py`: **5 tests passing** (queue triage, debouncing, confirm, reassign, enroll as new, dismiss).
  - `tests/test_enrollment.py`: **3 tests passing** (crop enrollment, frame + bbox enrollment, DualModelFeatureExtractor fusion).
  - `tests/test_occlusion_and_ema.py`: **4 tests passing** (track occlusion IoU checks, clutter Re-ID freeze, bounded EMA adaptation, drift rejection, version rollback).
  - `tests/test_m9_api.py`: **4 tests passing** (FastAPI endpoints for freeze-frame, universal enrollment, review queue actions, RSAC rules/categories CRUD, pet whitelist).
- Sphinx documentation build: **Passed with 0 warnings** (`sphinx -W --keep-going documentation/ documentation/_build/html/`).

---

## ✅ [Milestone 10] — VMS Dashboard Responsive Redesign, Ergonomics & Enterprise Hub Integration Readiness
**Status: COMPLETE** — Verified: 218/218 tests pass in Python 3.12.10; 0 Sphinx warnings.

### Objectives & Deliverables

1. **10a: Standardized Responsive Dialog Architecture & Scroll Containment**
   - Constrain `.modal-card` to `max-height: min(88dvh, 800px); display: flex; flex-direction: column`.
   - Add `.modal-body-scroll` internal scroll container with CSS scroll chaining containment (`overscroll-behavior: contain`).
   - Sticky `.modal-footer` guaranteeing action buttons remain visible.
   - Refactor `#modal-camera-manager`, `#modal-universal-enrollment`, `#modal-backup-manager`, `#modal-descriptor-versions`, and `#modal-review-reassign`.
   - Single-column responsive layout for modal grids on screens <800px.

2. **10b: In-Page Modal Forms & Modern Toast System (Eliminate `prompt()` / `alert()`)**
   - Replace sequential browser `prompt()` and `confirm()` alert chains in Scenario Studio and Review & Learn with dedicated in-page modal dialog forms:
     - `#modal-studio-zone`: Zone name, category filter, dwell threshold, capacity limit.
     - `#modal-studio-tripwire`: Tripwire name, bidirectional detection mode.
     - `#modal-studio-homography`: Ground plane metric width and height (meters).
     - `#modal-studio-transition`: Source/target cameras, zones, transit time ranges, and spatial prior boost.
     - `#modal-quick-enroll-entity`: Entity name and category picker.
   - Implement non-blocking toast notification system (`showToast()`) replacing all intrusive browser `alert()` popups.

3. **10c: Responsive Global Navigation & Header (Desktop, Tablet, Mobile)**
   - Add auto-scrolling horizontal navigation tab pill container with smooth snap scrolling.
   - Off-canvas slide-out navigation drawer (`#mobile-nav-drawer`) with hamburger toggle button (`#btn-mobile-menu`) for viewports <1024px.
   - Responsive breakpoints for all tab panes: stack sidebars and optimize media card viewports.

4. **10d: Foolproof Stream Reconnection & Unified VMS Player Architecture**
   - Fix Live Monitor image restoration bug: eliminate `img.src = ''` (which resolves to document URL), detach stream via neutral standby SVG poster, and reconnect with cache-buster `?t=${Date.now()}`.
   - Add unified player HUD overlay for Live Monitor matching Video Studio (Live pulse badge, stream pause/resume button, snapshot, aspect ratio selector, fullscreen, and resolution/bitrate telemetry).

5. **10e: Bidirectional URL Hash Routing**
   - Lightweight client-side hash router supporting `#live`, `#videos`, `#gallery`, `#timeline`, `#analytics`, `#alerts`, `#studio`, `#journey`, `#review`.
   - Support modal sub-routes: `#cameras`, `#enroll`, `#backup`, `#versions`.
   - Full browser Back and Forward navigation (`popstate` and `hashchange`).

6. **10f: Enterprise Hub Integration Readiness (Milestone 16d / Phase E5 Alignment)**
   - **HMAC-SHA256 Webhook Signing:** Update `intelligent_tracker.events.WebhookDispatcher` to accept `secret_key` and compute `X-Tracker-Signature` over payload bytes, including ISO-8601 UTC timestamp and `snapshot_base64`.
   - **HTTP Telemetry REST Endpoint:** Expose `GET /api/cameras/{camera_id}/telemetry` in `dashboard/app.py` returning active tracks, bounding boxes, and zone occupancy for central Hub HTML5 Canvas overlays.
   - **Offline-First SQLite Cache Tables:** Add `tracker_sync_state`, `local_whitelist`, and `offline_access_queue` to `intelligent_tracker.database.TrackerDB` conforming to `INTELLIGENT_TRACKER_OFFLINE_DB_SPEC.md`.

7. **10g: Automated Quality & Regression Tests**
   - Add `tests/test_dashboard_ui.py` testing HTML structure, modal scroll containment, API responses, and static asset integrity.
   - Run CDP layout audit via `cdp_inspect.py` in headless mode across desktop (1440x900), tablet (768x1024), and mobile (390x844) asserting `scrollWidth <= viewportWidth`.

---



---

## ✅ [Milestone 11] — Process Lifecycle Management, Zero-Load Hibernation & Runtime Diagnostics (COMPLETE)
**Status: COMPLETE** — Verified: 223/223 tests pass in Python 3.12.10 (Docker CPU: 0.66%)
**Scope:** Deep capture hibernation (`VideoSource.pause/resume`), self-healing leased subscriber registry (`StreamManager`), async disconnect detection (`Request.is_disconnected()`), enriched hardware & container runtime diagnostics (`scripts/diagnostics.py`), terminal stream controller (`scripts/stream_ctl.py`), SQLite resource telemetry persistence (`system_resource_metrics`, `stream_lifecycle_events`), and Superuser Admin REST APIs.

### Deliverables Completed:
1. **Deep Capture Hibernation (`intelligent_tracker/video.py`):** Added thread-safe `pause()` and `resume()` pausing OpenCV video decoding during stream hibernation to eliminate background frame processing.
2. **Leased Subscriber Registry (`dashboard/stream_manager.py`):** Self-healing registry with 3.0s lease TTL, auto-eviction of stale connections, and unified lock synchronization (`_subscriber_lock`).
3. **Async Disconnect Guard (`dashboard/app.py`):** Streaming generator detects client TCP disconnect immediately, terminating background tasks and preventing orphan loops.
4. **Enriched Diagnostics (`scripts/diagnostics.py`):** Added `--runtime` flag inspecting live Docker container CPU/RAM/PIDs, active stream states, and zombie task detection.
5. **Terminal Controller (`scripts/stream_ctl.py`):** CLI management commands: `list`, `stats`, `evict`, `prune`, `history`, `metrics`.
6. **Lifecycle Manager & Persistence (`intelligent_tracker/lifecycle.py` & `database.py`):** Background sampler recording CPU, RAM, and stream counts every 15s to SQLite tables `system_resource_metrics` and `stream_lifecycle_events`.
7. **Admin REST APIs (`dashboard/app.py`):** Superuser endpoints `/api/system/processes`, `/api/system/streams/{id}/evict`, `/api/system/hibernate_all`, `/api/system/metrics`, and `/api/system/events`.

## Dependency Graph

```
M1 (Env & Core) ✅
  └── M2 (ONNX Detectors) ✅
        └── M3 (RTSP + Spatial Analytics) ✅
              └── M4 (Re-ID Gallery & Sighting DB) ✅
                    └── M5 (Alerting + Entity Triggers) ✅
                          └── M6 (Dashboard + Edge Deploy) ✅
                                └── M7 (Multi-Camera VMS & Auto-Discovery) ✅
                                      └── M8 (World Scenario Studio & Homography BEV) ✅
                                            └── M9 (Artifact & Face Intelligence, Active Learning) ✅
                                                  └── M10 (VMS Dashboard Responsive Redesign & Hub Integration) ✅
                                                        └── M11 (Process Lifecycle Management & Zero-Load Hibernation) ✅
```

---

## Quick Reference

| Task | Command |
|---|---|
| Activate venv (Windows) | `.\.venv\Scripts\Activate.ps1` |
| Run tests | `$env:MPLBACKEND="Agg"; .\.venv\Scripts\python.exe -m unittest discover tests` |
| Run demo | `.\.venv\Scripts\python.exe main.py` |
| Install deps | `.\.venv\Scripts\pip.exe install -r requirements.txt` |
| Git status | `git status` |
