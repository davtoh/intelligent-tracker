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
| 3 | RTSP Streams & Retail/Occupancy Analytics | ⬜ Next |
| 4 | Event Dispatching & Alerting | ⬜ Planned |
| 5 | Web Dashboard, Packaging & Edge Deployment | ⬜ Planned |

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

## ⬜ [Milestone 3] — RTSP Camera Streams & Retail / Occupancy Analytics
**Scope:** Robust multi-source video ingestion, zone definition, person counting, heatmaps.

### Objectives

**3a — Non-blocking RTSP Video Reader:**
- `intelligent_tracker/video.py` — new module
  - `VideoSource` class: threaded frame reader with configurable buffer, auto-reconnect, frame-drop on lag
  - Sources: RTSP URLs (`rtsp://...`), USB webcam index, video file path, synthetic generator
  - Context manager (`with VideoSource(...) as vs:`) with clean shutdown
  - Connection health metrics: FPS, drop rate, reconnection count

**3b — Zone & Tripwire Geometry:**
- Extend `intelligent_tracker/geometry.py`:
  - `Tripwire(line_segment)`: bidirectional entry/exit crossing detection using centroid trajectory
  - `ZoneROI(polygon)`: polygon containment test (vectorized via `pointPolygonTest`)
  - `ZoneEvent` dataclass: `{zone_id, track_id, event_type: "enter"|"exit"|"dwell", timestamp}`
  - Integration with existing `Contour` / `Line` classes

**3c — Multi-Object Tracker:**
- `intelligent_tracker/tracker.py` — new module
  - `CentroidTracker`: IoU-based frame-to-frame ID assignment (no heavy dependencies)
  - Output: `Dict[track_id, Track]` where `Track` has bbox, centroid history, entry_time
  - Optional: SORT (Simple Online and Realtime Tracking) adapter using `numpy` only

**3d — Heatmap Engine:**
- `intelligent_tracker/analytics.py` — new module
  - `OccupancyHeatmap`: accumulate centroid positions over frames into 2D density array
  - Colormap overlay on camera frame (jet / inferno colormap, OpenCV `COLORMAP_JET`)
  - Export: PNG snapshot, CSV export, rolling-window reset

**3e — Analytics Dashboard (CLI / OpenCV window):**
- Real-time overlay: bounding boxes + track IDs + zone labels + occupancy counters
- Side panel: entry/exit tally per zone, current occupancy, dwell time
- Headless mode: write annotated frames to `output.mp4` file

**3f — Configuration:**
- `config.yaml` template for camera sources, zone polygons, model selection
- `--config path/to/config.yaml` CLI flag on `main.py`

### Verification
```powershell
# With synthetic source
.\.venv\Scripts\python.exe main.py --detector mock --source synthetic --config configs/demo.yaml

# With RTSP stream
.\.venv\Scripts\python.exe main.py --detector yolov8 --source rtsp://192.168.1.100/stream1 --config configs/retail.yaml

# Tests
.\.venv\Scripts\python.exe -m unittest discover tests
```

---

## ⬜ [Milestone 4] — Event Dispatching & Alerting System
**Scope:** Webhook, Telegram, and MQTT alerting on zone events.

### Objectives

**4a — Event Bus:**
- `intelligent_tracker/events.py`
  - `EventBus`: publish/subscribe, async dispatch queue (no dropped events)
  - `ZoneEvent`, `IntrusionAlert`, `OccupancyThresholdEvent` typed dataclasses
  - Thread-safe queue consumed by dispatcher workers

**4b — Webhook Dispatcher:**
- HTTP POST JSON payloads on: tripwire cross, zone intrusion, occupancy threshold breach
- Configurable URL, auth header, retry logic (3 retries, exponential backoff)
- Payload includes: `camera_id`, `zone_id`, `event_type`, `timestamp`, optional base64 snapshot

**4c — Telegram Bot:**
- `python-telegram-bot` integration
- Alert message with snapshot attachment on intrusion or threshold
- Rate limiting: configurable cooldown (default 60s per zone per event type)
- `/status` command returns live occupancy summary

**4d — MQTT Publisher:**
- `paho-mqtt` based publisher
- Topics: `tracker/{camera_id}/occupancy`, `tracker/{camera_id}/events`
- Home Assistant / Node-RED compatible JSON payloads
- Retained messages for occupancy counts

**4e — Configurable Rules:**
- Quiet hours (time-of-day schedule per zone)
- Alert cooldowns to prevent fatigue
- Minimum confidence threshold per event type

### Verification
```powershell
# Webhook test (local echo server)
.\.venv\Scripts\python.exe -m tests.test_events

# MQTT test (mosquitto local broker)
.\.venv\Scripts\python.exe main.py --config configs/alert_demo.yaml
```

---

## ⬜ [Milestone 5] — Web Dashboard, Packaging & Edge Deployment
**Scope:** Modern live web dashboard, Docker containers, systemd service, Sphinx docs.

### Objectives

**5a — FastAPI + WebSocket Dashboard:**
- `dashboard/` directory — FastAPI app
  - Live MJPEG stream endpoint: `GET /stream/{camera_id}`
  - WebSocket metrics endpoint: `WS /ws/{camera_id}` — pushes occupancy JSON 10× per second
  - REST API: `GET /cameras`, `GET /zones`, `GET /analytics/heatmap`, `GET /events`
- React or plain HTML5 + Chart.js frontend:
  - Live annotated camera feed
  - Zone occupancy counters (real-time)
  - Entry/exit time series chart (last 1h)
  - Heatmap overlay toggle
  - Alert history log

**5b — Raspberry Pi & Edge Deployment:**
- `Dockerfile.arm64` + `Dockerfile.amd64` (multi-stage: builder + slim runtime)
- `docker-compose.yml`: `tracker` service + `dashboard` service + optional `mosquitto` MQTT broker
- `deployment/intelligent-tracker.service` — systemd unit for Raspberry Pi OS / Ubuntu
- Hardware acceleration flags:
  - Coral Edge TPU delegate (`pycoral`/`tflite-runtime`) for RPi
  - `libcamera` source support for Raspberry Pi Camera Module v3
  - Intel NUC: `onnxruntime-openvino`

**5c — CI/CD:**
- `.github/workflows/ci.yml`: install deps → test → lint (ruff) → optional Docker build
- Badge on `README.rst`

**5d — Sphinx Documentation Modernization:**
- Update `documentation/conf.py` for Sphinx 7+
- Auto-generate API reference for new modules (`video.py`, `tracker.py`, `analytics.py`, `events.py`)
- Architecture diagram (Mermaid or draw.io)
- ReadTheDocs deployment (`.readthedocs.yml` already present)

**5e — `install_opencv.sh` update:**
- Ensure `install_opencv.sh` works for Raspberry Pi OS Bookworm (64-bit) and Ubuntu 24.04

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
  └── M2 (ONNX Detectors)
        └── M3 (RTSP + Analytics)
              └── M4 (Alerting)
                    └── M5 (Dashboard + Edge Deploy)
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
