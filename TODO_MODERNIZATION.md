# Intelligent Tracker Modernization Roadmap

**Project:** Intelligent Tracker (Pi / Smart Cameras)  
**Status:** In Progress (Revitalizing 8-year legacy code to modern Edge AI stack)  
**Target Environments:** Windows (Development/Current), Linux (Raspberry Pi OS / Ubuntu / Debian), macOS (Apple Silicon / Intel)  
**Core Vision:** Transform legacy Haar cascade CCTV tracking into a lightweight Edge AI retail & security analytics platform with real-time zone counting, heatmaps, RTSP streaming, and instant webhook/MQTT/Telegram alerts.

---

## Modernization Phases & Milestones

### Phase 1: Environment & Core Engine Revitalization (In Progress)
- [x] **Audit Codebase & Dependencies**: Discover legacy requirements (`combomethod`, `future`, `six`, `resource`, `opencv-contrib-python`).
- [x] **Establish Modern Python 3.12 Virtual Environment (`.venv`)**:
  - Windows: `py -3.12 -m venv .venv` with upgraded `pip`, `setuptools`, and `wheel`.
  - Maintain historical Conda (`InteligentTracker` Python 3.7) reference for backward verification.
- [x] **Cross-Platform Compatibility Fixes**:
  - Replace Unix-only `resource` module in `tests/test_core.py` with cross-platform `psutil` / graceful fallback.
  - Remove defunct external dependency `RRtoolbox` imports.
  - Preserve all developer rationale comments and legacy formulas per rule `comment_preservation.md`.
- [x] **Establish Modern Project Rules**:
  - Adapt `rules/comment_preservation.md` for computer vision & legacy ML annotations.
  - Adapt `rules/environment_and_execution.md` with exact paths and cross-platform instructions.
  - Adapt `rules/milestone_workflow.md` with structured verification steps.
  - Adapt `rules/security_and_standards.md` for RTSP secrets, GDPR privacy, and frame buffer safety.
  - Adapt `rules/task_logging.md` for persistent state preservation.
- [ ] **Cross-Platform Setup Documentation (`SETUP_GUIDE.md`)**:
  - Step-by-step setup for Windows, Linux (Debian/Ubuntu/Raspberry Pi OS), and macOS.
  - Instructions for headless/server deployment (`opencv-python-headless`, offscreen rendering).
- [ ] **Verify Test Suite**:
  - Run `test_geometry.py`, `test_core.py`, and `test_forms.py` cleanly in Python 3.12.
- [ ] **Smoke Test Main Application**:
  - Enable synthetic/mock camera mode in `main.py` so demo runs reliably without physical camera hardware attached.

---

### Phase 2: Edge AI Detection Architecture (COMPLETE ✅)
- [x] **Modular Detector Interface**:
  - `BaseDetector` abstract class and `Detection` namedtuple in `intelligent_tracker.detectors`.
  - Concrete adapters for `HaarCascadeDetector` and `ColorDetector`.
- [x] **YOLOv8 / YOLOv11 Edge Integration**:
  - Zero-dependency `OnnxDetector` using ONNX Runtime with execution provider cascade (CUDA -> DirectML -> OpenVINO -> CoreML -> CPU).
  - Pure NumPy letterbox resizing and multi-class Non-Maximum Suppression (NMS).
  - Automatic download & checksum verification via `scripts/download_models.py`.
- [x] **Multi-Class Detection & CLI**:
  - Full COCO class filtering (`--classes person car`).
  - Comprehensive unit test suite with 46 tests passing.

---

### Phase 3: RTSP Camera Streams & Retail / Occupancy Analytics
- [ ] **Robust RTSP Video Ingestion Pipeline**:
  - Threaded non-blocking RTSP frame reader with automatic reconnection and frame-drop policy (zero latency drift).
  - Support multiple camera inputs (IP cameras, USB webcams, RTSP streams, video test files).
- [ ] **Zone Definition & Spatial Geometry**:
  - Virtual tripwires (entry/exit bidirectional counting).
  - Polygonal ROI zones (dwell areas, queue zones, checkout counters).
  - Intersection algorithms utilizing `intelligent_tracker.geometry` with NumPy vectorization.
- [ ] **Multi-Object Tracking (Short-Term)**:
  - `CentroidTracker` / SORT for frame-to-frame association while objects remain in field of view.
- [ ] **Retail Analytics Engine**:
  - Real-time occupancy tracking (current occupants, entries, exits).
  - Dwell time estimation per zone.
  - Heatmap generation (2D occupancy density accumulation mapped over camera frames).

---

### Phase 4: Object Identity Gallery, Re-Identification (Re-ID) & Sighting Database
- [ ] **Persistent SQLite Database (`tracker.db`)**:
  - `entities`: `(id, name, category, status, notes, timestamps)`.
  - `entity_signatures`: `(id, entity_id, embedding_blob, crop_path)`.
  - `sightings`: `(id, entity_id, track_id, source, timestamp, zone_id, bbox, confidence, snapshot)`.
- [ ] **Visual Feature Descriptors & Re-ID Embeddings**:
  - Lightweight ONNX Re-ID feature extractor (`osnet_x0_25.onnx` / `mobilenetv3_reid.onnx`).
  - Ultra-lightweight spatial HSV color histogram fallback for Raspberry Pi CPU.
  - Cosine similarity matching against enrolled gallery in SQLite.
- [ ] **Interactive Screen Selection & Tagging**:
  - Mouse click on bounding box in live view or paused recording to select object.
  - Dialog / prompt to assign name (e.g. "Forklift 02", "Alice"), category ("VIP", "Staff", "Authorized"), and notes.
- [ ] **Cross-Session Re-Appearance Engine**:
  - Automatic identification when previously enrolled entity appears again in live stream or different camera.
  - Audit logging of all sightings into database.
- [ ] **Offline Recording Indexer & Analytics**:
  - Batch process recorded video files to index all appearances.
  - Sighting timeline and frequency/dwell-time query reports.

---

### Phase 5: Event Dispatching & Alerting System
- [ ] **Webhook Dispatcher**:
  - HTTP POST event payloads (JSON) on tripwire cross, zone intrusion, occupancy breach, or tagged entity sighting.
- [ ] **Telegram Bot Integration**:
  - Instant alert messages with snapshot attachments on intrusion, threshold, or recognized VIP/restricted entity.
- [ ] **MQTT Broker Publisher**:
  - Lightweight telemetry (`tracker/{camera_id}/occupancy`, `tracker/{camera_id}/sightings/{entity_id}`).
- [ ] **Configurable Rules & Entity Filters**:
  - Quiet hours, alert cooldowns, and entity-specific triggers (e.g. alert if restricted vehicle appears).

---

### Phase 6: Modern Web Dashboard, Packaging & Edge Deployment
- [ ] **Modern Web Analytics Dashboard**:
  - FastAPI + WebSocket backend with live MJPEG camera streams.
  - React / HTML5 frontend with real-time zone counters, heatmaps, and alert logs.
  - **Entity Gallery View**: Browse enrolled people/objects, view appearance timelines, click-to-tag in browser.
- [ ] **Raspberry Pi OS / Edge Deployment**:
  - Systemd service configurations and Docker containerization (`Dockerfile` for ARM64 and x86_64).
  - Hardware acceleration flags (OpenVINO, Coral Edge TPU delegate, Raspberry Pi Camera Module `libcamera`).
- [ ] **Documentation & Sphinx Modernization**:
  - Refresh Sphinx configuration and generate clean HTML documentation.
  - Update `README.md` with architecture diagrams and quickstart examples.
