# Changelog

## [2026-11-09] feat: System Capabilities API & Camera AI Configuration Modal (Milestone 2)
- **Type**: feat
- **Summary**: Implemented dynamic AI capabilities discovery endpoint (`/api/system/capabilities`) exposing detectors, trackers, Re-ID extractors, and COCO classes. Extended the VMS camera modal with an AI Detector & Tracking Intelligence section, bidirectional confidence slider/numeric inputs, class filter presets, and quick physical webcam presets. Normalized SortTracker and CentroidTracker kwargs (`max_age` / `max_disappeared`).
- **Files** (8):
  - `dashboard/routers/system.py`
  - `dashboard/camera_pool.py`
  - `dashboard/services/pipeline_factory.py`
  - `intelligent_tracker/tracker/sort.py`
  - `dashboard/static/css/camera_ai_config.css`
  - `dashboard/static/js/camera_ai_config.js`
  - `dashboard/static/camera_manager.js`
  - `dashboard/static/index.html`
  - `tests/test_camera_detector_config.py`
- **Verification**: 317/317 tests pass (36.71s); 0 warnings Sphinx HTML build.

## [2026-11-09] feat: Dynamic Detector & Pipeline Configuration (Milestone 1)
- **Type**: feat
- **Summary**: Implemented dynamic Edge AI detector selection, confidence thresholds, and class filtering contracts across Pydantic schemas, CameraPool orchestrator, StreamPipelineFactory, and VideoRouter. Fixed broken VideoIndexer offline batch occurrence analytics import and parameterized feed promotion.
- **Files** (7):
  - `dashboard/schemas.py`
  - `dashboard/camera_pool.py`
  - `dashboard/routers/cameras.py`
  - `dashboard/routers/videos.py`
  - `dashboard/services/pipeline_factory.py`
  - `intelligent_tracker/batch.py`
  - `tests/test_camera_detector_config.py`
- **Verification**: 315/315 tests pass (36.01s); Sphinx HTML build succeeds with 0 warnings.

## [2026-11-06] feat: Universal Runtime Trace Recorder & Dashboard Boot Resilience
- **Type**: feat
- **Summary**: Integrated global trace_recorder engine into system-diagnostics and wired FastAPI exception middleware. Fixed uvicorn reload directory watcher bounds, camera pool offline state handling, and spawned process PYTHONPATH propagation on Windows.
- **Files** (4):
  - `dashboard/app.py`
  - `dashboard/camera_pool.py`
  - `dashboard/services/diagnostic_bridge.py`
  - `scripts/run_dashboard.py`
- **Verification**: 308 tests passed in intelligent_tracker (36.99s); 116 tests passed in system-diagnostics (3.64s)

## [2026-11-05] fix: Thread Safety, 12-Factor Env and Defensive Logging Fixes
- **Type**: fix
- **Summary**: Implemented interruptible Event.wait in WebhookDispatcher, MqttPublisher, and LifecycleManager; parameterized MQTT_BROKER; replaced JS empty catch blocks with console.debug
- **Files** (9):
  - `MIGRATION_LOG.md`
  - `dashboard/static/js/telemetry.js`
  - `dashboard/static/js/text_truncation_manager.js`
  - `dashboard/static/video_scrubber.js`
  - `intelligent_tracker/events/mqtt.py`
  - `intelligent_tracker/events/webhooks.py`
  - `intelligent_tracker/lifecycle.py`
  - `tests/test_events_dispatchers.py`
  - ... (+1 more)
- **Verification**: diagnose.py tests (308 passed, 0 regressions)
## [Milestone 1] - 2026-10-21 - Environment & Core Engine Revitalization

### 1. Objectives & Scope
- Revitalize 8-year legacy computer vision project (CCTV / Raspberry Pi object tracking).
- Set up a clean, modern Python 3.12 64-bit environment (`.venv`) while maintaining knowledge of historical Anaconda 3.7 (`InteligentTracker`) environment.
- Adapt project rules (`rules/*.md`) from previous Django template to Intelligent Tracker computer vision, RTSP edge security, and modern Python guidelines.
- Diagnose and fix immediate cross-platform compatibility blockers in tests (e.g. Unix-only `resource` module, defunct `RRtoolbox` imports).
- Prepare cross-platform setup guide (`SETUP_GUIDE.md`) for Windows, Linux (Raspberry Pi / Debian / Ubuntu), and macOS.
- Build modernization roadmap (`TODO_MODERNIZATION.md`) addressing YOLOv8/v11 Edge, RTSP analytics, and alerting.

### 2. Files Touched
- `rules/comment_preservation.md`: Adapted examples to OpenCV, Haar cascades, and computer vision mathematics.
- `rules/environment_and_execution.md`: Updated virtualenv paths, test commands, execution workflows, and cross-platform instructions.
- `rules/milestone_workflow.md`: Structured incremental computer vision milestones and automated verification procedures.
- `rules/security_and_standards.md`: Added RTSP camera secret handling, GDPR video privacy, OpenCV frame buffer memory leak safety, and modern Python standards.
## [Milestone 2] - 2026-10-23 - Edge AI Detection Architecture

### 1. Objectives & Scope
- Modernize the legacy Haar cascade detection architecture into an extensible, pluggable Edge AI framework.
- Integrate ultralightweight Edge AI models (**YOLOv8 Nano**, **YOLO11 Nano**) via **ONNX Runtime** without requiring heavy PyTorch or CUDA dependencies on edge devices.
- Design an abstract `BaseDetector` interface defining a typed contract returning `Detection(bbox, class_id, confidence, label)` namedtuples.
- Create a registry-based `DetectorFactory` providing decoupled instantiation by name (`"haar"`, `"yolov8"`, `"yolo11"`, `"mock"`, `"color"`, `"face"`, `"eye"`), with bidirectional registration into `Detector.available_detectors`.
- Implement zero-dependency computer vision primitives in pure NumPy:
  - Letterbox aspect-ratio preserving resizing with constant border padding.
  - Vectorized multi-class Non-Maximum Suppression (NMS) with label offsets.
  - Letterbox-to-original coordinate space inverse transformation strictly bounded to image boundaries.
- Build automatic Execution Provider fallback hierarchy in ONNX Runtime:
  `CUDAExecutionProvider` -> `DmlExecutionProvider` (DirectML on Windows) -> `OpenVINOExecutionProvider` (Intel) -> `CoreMLExecutionProvider` (macOS) -> `CPUExecutionProvider`.
- Maintain full backwards compatibility for legacy detectors:
  - `HaarCascadeDetector`: Subclass of `BaseDetector` and `Detector` wrapping OpenCV cascade XML files.
## [Milestone 3] - 2026-10-23 - RTSP Camera Streams & Retail / Occupancy Analytics

### 1. Objectives & Scope
- Deliver non-blocking, multi-source video ingestion supporting RTSP IP network streams, local webcams, video files, and high-fidelity synthetic feeds.
- Build a dedicated background acquisition reader (`VideoSource`) with configurable buffer queues, automatic frame-drop on lag (guaranteeing zero latency drift for live streams), auto-reconnect backoff on network dropouts, and live connection health metrics (FPS, drop rate %, frames read, reconnections).
- Extend `intelligent_tracker.geometry` with spatial analytics primitives:
  - `Tripwire`: Virtual line segment with trajectory vector normal analysis for bidirectional entry/exit crossing detection and tally counters.
  - `ZoneROI`: Polygonal region of interest using `cv2.pointPolygonTest` with occupant state machine, entry/exit/dwell events, dwell time estimation, and translucent overlay rendering.
  - `ZoneEvent` and `TripwireEvent`: Strongly typed dataclasses with dictionary serialization.
  - Integrated `Area` and `Line` in `intelligent_tracker/high_objects.py` to wrap `ZoneROI` and `Tripwire`.
- Implement multi-object tracking in `intelligent_tracker.tracker`:
  - `Track`: Rich entity representation with centroid motion history, smoothed velocity estimation, dwell times, and state lifecycle (`tentative`, `confirmed`, `lost`).
  - `CentroidTracker`: Two-stage IoU and Euclidean distance matching with zero heavy dependencies.
  - `SortTracker`: Simple Online and Realtime Tracking using 2D kinematic Kalman filters in pure NumPy.
  - `TrackerFactory`: Registry for decoupled runtime instantiation (`centroid`, `sort`).
## [Hardware & GUI Stabilization: Camera Auto-Detection & DirectShow Driver Unbind Cooldown] - 2026-10-23

### 1. Objectives & Scope
- **DirectShow Unbind Race Condition Resolution**:
  - Diagnosed a race condition on Windows where probing device indices with DirectShow (`cv2.CAP_DSHOW`) left the kernel UVC device handle in a brief unbinding transition (~0.35s).
  - When `find_first_real_camera` probed device index `0` and immediately released it with only a `0.05s` delay, a subsequent `cv2.VideoCapture(0, cv2.CAP_DSHOW)` in `VideoSource` found index `0` momentarily locked; DirectShow silently routed capture to the next available filter in the category (OBS Virtual Camera at index `1`).
  - Added an unbind cooldown of `0.45s` on Windows in `find_first_real_camera` and `find_physical_cameras`, plus a transition settle check on index 0 to ensure deterministic, exclusive binding to the physical camera.
- **Physical vs Virtual Camera Discrimination**:
  - `is_physical_camera(cap)`: Distinguishes physical UVC hardware webcams from virtual software devices (OBS Virtual Camera, GoPro Webcam, ManyCam) by querying UVC hardware sensor registers (`CONTRAST`, `SHARPNESS`, `GAIN`, `SATURATION`, `BRIGHTNESS`). Virtual cameras return `-1.0` for all hardware registers.
  - `resolve_camera_source(source)`: Automatically resolves `'real'`, `'auto'`, `'physical'`, `'hardware'`, or `'webcam'` to the first verified physical webcam, emitting clear console notifications (`[INFO] Auto-detected real physical camera at device index #0`), while warning and falling back safely to index `0` when disconnected (`[WARN] No physical hardware camera found with real data; defaulting to device index 0.`). Preserves numeric indices (`0`, `1`) deterministically.
- **Interactive OpenCV HUD & Screen Inspection (`--gui opencv`)**:
  - Left-click on any tracked bounding box in the GUI to inspect target telemetry (Track ID, label, confidence, dwell duration in seconds, velocity). Click in empty space to deselect.
  - Spacebar: Real-time pause/resume without resetting tracking state.
  - `d`: Clear/reset tracks and active target selection.
  - Window `[X]` button / `q` / `ESC`: HighGUI event loop flushing and clean termination.
## [Milestone 4] - 2026-10-24 - Object Identity Gallery, Re-Identification (Re-ID) & Sighting Database

### 1. Objectives & Scope
- Deliver a persistent, embedded SQLite database (`TrackerDB` in `intelligent_tracker/database.py`) managing:
  - `entities`: Name, category (`person`, `vehicle`, `vip`, `staff`, `visitor`, `delivery`), status, notes, timestamps.
  - `entity_signatures`: Multi-dimensional feature vector BLOBs and representative thumbnail crops.
  - `sightings`: Full chronological audit trail of where and when each entity was seen (track ID, camera source, timestamp, zone, bbox, confidence).
  - Compound indexes on `(entity_id, timestamp)` and `(source, timestamp)` for rapid historical lookup.
  - Comprehensive occurrence analytics (dwell duration approximation, distinct sources, zone journeys, JSON/CSV exports).
- Implement visual Re-ID feature extractors in `intelligent_tracker/reid.py`:
  - `BaseFeatureExtractor`: Abstract interface returning L2-normalized float32 vectors.
  - `OnnxReIDExtractor`: Deep visual embedding extractor via ONNX Runtime with multi-platform execution provider cascade (CUDA -> DirectML -> OpenVINO -> CoreML -> CPU). Includes support for both dynamic and fixed batch architectures (e.g. OSNet x0.25).
  - `ColorHistogramExtractor`: Ultra-lightweight CPU fallback using spatial-grid joint 3D HSV color histograms (zero neural network dependency, pure NumPy/OpenCV, sub-millisecond on Raspberry Pi CPU). Reconnects directly to the original project's descriptor vision (`self.descriptors`).
  - `MockFeatureExtractor`: Deterministic synthetic feature generator for automated CI and headless testing.
  - Vectorized `batch_cosine_similarity` for matrix-vector gallery matching.
## [Milestone 5] - 2026-10-24 - Event Dispatching & Alerting System

### 1. Objectives & Scope
- Design and implement a centralized, asynchronous, thread-safe publish-subscribe Event Bus (`EventBus`) with zero dropped events and error containment.
- Implement typed event dataclasses: `BaseEvent`, `ZoneEvent`, `TripwireCrossEvent`, `IntrusionAlert`, `OccupancyThresholdEvent`, `EntityIdentifiedEvent`, `RestrictedEntityAlert`.
- Provide base64 JPEG snapshot serialization and cropping helpers (`frame_to_base64`, `crop_to_base64`, `decode_snapshot_base64`).
- Build HTTP POST Webhook Dispatcher (`WebhookDispatcher`) with exponential backoff retry logic (3 retries), Bearer/custom authentication, and event type filtering.
- Build Telegram Bot Dispatcher (`TelegramDispatcher`) with rich Markdown alert formatting, status emojis (🚨, ⚠️, 👤, 🛑), photo attachment upload (`sendPhoto`), rate-limiting cooldown per entity/zone, and interactive `/status`, `/occupancy`, `/help` query command responders.
- Build MQTT Telemetry Publisher (`MqttPublisher`) compatible with Home Assistant and Node-RED:
  - Occupancy topic: `tracker/{camera_id}/occupancy` (retained).
  - Event stream: `tracker/{camera_id}/events` (unretained).
  - Sighting topic: `tracker/{camera_id}/sightings/{entity_id}` (retained).
  - Last Will & Testament (LWT) topic: `tracker/system/status` (`"online"` / `"offline"`).
  - Supports modern Paho MQTT 2.x (`CallbackAPIVersion.VERSION2`) with graceful fallback to 1.x and offline mock mode.
- Build Quiet Hours & Alert Rule Engine (`QuietHours`, `AlertRule`, `AlertRuleEngine`):
## [Milestone 6] - 2026-10-24 - Web Dashboard, Packaging & Edge Deployment

### 1. Objectives & Scope
- **6a — Modern Web Analytics Dashboard (FastAPI + WebSockets + HTML5/CSS/JS):**
  - Built standalone, high-performance web dashboard application in `dashboard/app.py` powered by FastAPI, Uvicorn, and Starlette.
  - Live multipart MJPEG streaming endpoint: `GET /stream/{camera_id}` with boundary frame streaming and adaptive quality compression.
  - Bidirectional WebSocket telemetry feed: `WS /ws/{camera_id}` pushing real-time active tracks, dwell durations, velocities, zone occupancies, tripwire tallies, and alert events.
  - REST API surface:
    - `GET /cameras`: Available camera feeds and operational statuses.
    - `GET /zones`: Zone names, vertices, current occupancies, capacity limits, and breach states.
    - `GET /analytics/heatmap`: False-color density overlay (JPEG) or raw 2D spatial grid (JSON).
    - `POST /analytics/heatmap/toggle`: Dynamic toggle for real-time heatmap display on video.
    - `GET /entities`, `POST /entities`, `GET /entities/{entity_id}`, `DELETE /entities/{entity_id}`: Full CRUD lifecycle for enrolled identities.
    - `GET /sightings`: Chronological sighting queries with filtering by entity, zone, and time range.
    - `GET /events`: Recent alert log from EventBus history.
## [Milestone 7] - 2026-10-26 - Multi-Camera VMS, Auto-Discovery & Video Source Manager

### 1. Objectives & Scope
- Design and implement an enterprise-grade Multi-Camera Video Management System (VMS) with dynamic runtime stream orchestration.
- Implement dual auto-discovery capabilities in `intelligent_tracker/discovery.py`:
  - Physical USB webcams & local capture devices probing using DirectShow on Windows (`cv2.CAP_DSHOW`) and V4L2/Default on Linux.
  - LAN network camera discovery via ONVIF WS-Discovery (UDP 3702 multicast to `239.255.255.250`) and concurrent subnet RTSP port scanning (`554`, `8554`, `8000`).
  - One-click source connectivity tester with fast socket pre-checks, resolution/FPS retrieval, and base64 JPEG snapshot for live browser preview.
  - Built-in vendor presets with URL-encoded credential builder (`urllib.parse.quote`) for Hikvision, TP-Link Tapo, EZVIZ, Dahua/Imou, and Generic RTSP.
- Implement dynamic multi-stream pool orchestrator (`dashboard/camera_pool.py`):
  - Hot-add, configure, toggle, and remove streams dynamically at runtime without restarting the FastAPI server.
  - Automatic boot restoration of configured streams from `configs/cameras.json`.
  - Independent background worker threads with thread-safe telemetry distribution.
- Implement local video recording studio & scrubber:
  - Video upload support (`.mp4`, `.avi`, `.mkv`, `.mov`) into `data/videos/`.
