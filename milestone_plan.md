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
| 5 | Event Dispatching & Alerting System | ⬜ Next |
| 6 | Web Dashboard, Packaging & Edge Deployment | ⬜ Planned |

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

## ⬜ [Milestone 5] — Event Dispatching & Alerting System
**Scope:** Webhook, Telegram, and MQTT alerting on zone events, tripwires, and tagged entity recognition.

### Objectives

**5a — Event Bus:**
- `intelligent_tracker/events.py`
  - `EventBus`: publish/subscribe, async dispatch queue (no dropped events).
  - Typed dataclasses: `ZoneEvent`, `IntrusionAlert`, `OccupancyThresholdEvent`, `EntityIdentifiedEvent`, `RestrictedEntityAlert`.
  - Thread-safe queue consumed by dispatcher workers.

**5b — Webhook Dispatcher:**
- HTTP POST JSON payloads on: tripwire cross, zone intrusion, occupancy breach, or specific entity sighting.
- Configurable URL, auth header, retry logic (3 retries, exponential backoff).
- Payload includes: `camera_id`, `zone_id`, `entity_id`, `entity_name`, `event_type`, `timestamp`, optional base64 snapshot.

**5c — Telegram Bot:**
- `python-telegram-bot` integration.
- Alert message with snapshot attachment on intrusion, threshold, or recognized VIP/restricted entity.
- Rate limiting: configurable cooldown (default 60s per zone/entity).
- `/status` command returns live occupancy summary and recent sightings.

**5d — MQTT Publisher:**
- `paho-mqtt` based publisher.
- Topics: `tracker/{camera_id}/occupancy`, `tracker/{camera_id}/events`, `tracker/{camera_id}/sightings/{entity_id}`.
- Home Assistant / Node-RED compatible JSON payloads.
- Retained messages for occupancy counts and last known entity locations.

**5e — Configurable Rules & Entity Filters:**
- Quiet hours (time-of-day schedule per zone).
- Entity triggers: e.g. *"Alert if category=='restricted' enters Zone A"*, *"Log if category=='staff' arrives"*.
- Alert cooldowns to prevent notification fatigue.

### Verification
```powershell
# Webhook test (local echo server)
.\.venv\Scripts\python.exe -m tests.test_events

# MQTT test (mosquitto local broker)
.\.venv\Scripts\python.exe main.py --config configs/alert_demo.yaml
```

---

## ⬜ [Milestone 6] — Web Dashboard, Packaging & Edge Deployment
**Scope:** Modern live web dashboard with entity gallery and sighting search, Docker containers, systemd service, Sphinx docs.

### Objectives

**6a — FastAPI + WebSocket Dashboard:**
- `dashboard/` directory — FastAPI app
  - Live MJPEG stream endpoint: `GET /stream/{camera_id}`
  - WebSocket metrics endpoint: `WS /ws/{camera_id}` — pushes occupancy and sighting JSON in real time.
  - REST API: `GET /cameras`, `GET /zones`, `GET /analytics/heatmap`, `GET /entities`, `GET /sightings`.
- React or plain HTML5 + Chart.js frontend:
  - Live annotated camera feed with interactive click-to-tag bounding box capability in browser.
  - **Entity Gallery View**: Grid of enrolled people/objects, category badges, appearance counts.
  - **Sighting Timeline Player**: Search sightings by entity name, date/time range, or zone.
  - Zone occupancy counters and entry/exit time series charts.
  - Heatmap overlay toggle and alert history log.

**6b — Raspberry Pi & Edge Deployment:**
- `Dockerfile.arm64` + `Dockerfile.amd64` (multi-stage: builder + slim runtime).
- `docker-compose.yml`: `tracker` service + `dashboard` service + optional `mosquitto` MQTT broker.
- `deployment/intelligent-tracker.service` — systemd unit for Raspberry Pi OS / Ubuntu.
- Hardware acceleration flags:
  - Coral Edge TPU delegate (`pycoral`/`tflite-runtime`) for RPi.
  - `libcamera` source support for Raspberry Pi Camera Module v3.
  - Intel NUC: `onnxruntime-openvino`.

**6c — CI/CD:**
- `.github/workflows/ci.yml`: install deps → test → lint (ruff) → optional Docker build.
- Badge on `README.rst`.

**6d — Sphinx Documentation Modernization:**
- Update `documentation/conf.py` for Sphinx 7+.
- Auto-generate API reference for new modules (`video.py`, `tracker.py`, `database.py`, `reid.py`, `analytics.py`, `events.py`).
- Architecture diagram (Mermaid or draw.io).
- ReadTheDocs deployment (`.readthedocs.yml` already present).

**6e — `install_opencv.sh` update:**
- Ensure `install_opencv.sh` works for Raspberry Pi OS Bookworm (64-bit) and Ubuntu 24.04.

### Verification
```powershell
# Dashboard
.\.venv\Scripts\python.exe -m uvicorn dashboard.app:app --reload
# Open http://localhost:8000

# Docker (Linux/macOS)
docker compose up --build
docker compose exec tracker python -m unittest discover tests

# Sphinx docs
.\.venv\Scripts\python.exe -m sphinx documentation/ documentation/_build/html/
```

---

## Untracked Files Assessment

| File | Recommendation | Reasoning |
|---|---|---|
| `dev_tracker.mdj` | ➕ Add to `.gitignore` | StarUML binary design file (518KB). Binary, large, tool-specific. Not useful in repo unless team uses StarUML. |
| `intelligent_tracker.uml` | ➕ Add to `.gitignore` | Legacy UML file (17KB). Likely auto-generated or stale. Prefer Mermaid diagrams in docs. |
| `tests/servo_caracterization.py` | ➕ Commit with note | Historical servo motor characterization experiment for PTZ camera pan/tilt control. Contains calibrated polynomial regression coefficients (steps/delay/velocity mapping). **Valuable domain knowledge** for future PTZ/gimbal control milestone. Add to `tests/experimental/`. |

---

## Dependency Graph

```
M1 (Env & Core) ✅
  └── M2 (ONNX Detectors) ✅
        └── M3 (RTSP + Spatial Analytics)
              └── M4 (Re-ID Gallery & Sighting DB)
                    └── M5 (Alerting + Entity Triggers)
                          └── M6 (Dashboard + Edge Deploy)
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
