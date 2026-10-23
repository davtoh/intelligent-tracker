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

### Phase 2: Edge AI Detection Architecture (Haar Cascades -> YOLOv8 / YOLOv11 Edge)
- [ ] **Modular Detector Interface**:
  - Refactor `intelligent_tracker.detectors` to define an abstract `BaseDetector` interface.
  - Maintain legacy `HaarCascadeDetector` and `ColorDetector` as fallback options.
- [ ] **YOLOv8 / YOLOv11 Edge Integration**:
  - Support ultralightweight models (`yolov8n.onnx`, `yolov11n.onnx`, `yolo11n-pose.onnx`).
  - Add native inference via **ONNX Runtime** (CPU, DirectML on Windows, OpenVINO on Intel, and Edge TPU / Coral on Raspberry Pi).
  - Implement zero-dependency ONNX pre/post-processing (letterbox resizing, NMS suppression) without requiring heavy PyTorch on edge devices.
- [ ] **Multi-Class Detection & Classification**:
  - Person detection (`class_id=0`), vehicle detection, or custom retail objects.
  - Optional face/anonymization detector for privacy compliance.

---

### Phase 3: RTSP Camera Streams & Retail / Occupancy Analytics
- [ ] **Robust RTSP Video Ingestion Pipeline**:
  - Threaded non-blocking RTSP frame reader with automatic reconnection and frame-drop policy (zero latency drift).
  - Support multiple camera inputs (IP cameras, USB webcams, RTSP streams, video test files).
- [ ] **Zone Definition & Spatial Geometry**:
  - Virtual tripwires (entry/exit bidirectional counting).
  - Polygonal ROI zones (dwell areas, queue zones, checkout counters).
  - Intersection algorithms utilizing `intelligent_tracker.geometry` with NumPy vectorization.
- [ ] **Retail Analytics Engine**:
  - Real-time occupancy tracking (current occupants, entries, exits).
  - Dwell time estimation per zone.
  - Heatmap generation (2D occupancy density accumulation mapped over camera frames).

---

### Phase 4: Event Dispatching & Alerting System
- [ ] **Webhook Dispatcher**:
  - HTTP POST event payloads (JSON) on tripwire cross, zone intrusion, or occupancy threshold breach.
- [ ] **Telegram Bot Integration**:
  - Instant alert messages with optional snapshot frame attachments on intrusion or alert trigger.
- [ ] **MQTT Broker Publisher**:
  - Lightweight telemetry publication (`tracker/{camera_id}/occupancy`, `tracker/{camera_id}/events`) for integration with Home Assistant, Node-RED, or enterprise dashboards.
- [ ] **Configurable Rules & Quiet Hours**:
  - Cooldown periods to prevent alert fatigue.
  - Time-of-day schedules for intrusion vs retail modes.

---

### Phase 5: Modern Web Dashboard, Packaging & Edge Deployment
- [ ] **Modern Web Analytics Dashboard**:
  - Lightweight FastAPI / WebSocket or Streamlit / Next.js live monitoring dashboard.
  - Live RTSP stream overlay with heatmaps, bounding boxes, and real-time counter metrics.
- [ ] **Raspberry Pi OS / Edge Deployment**:
  - Systemd service configurations and Docker containerization (`Dockerfile` for ARM64 and x86_64).
  - Hardware acceleration flags (OpenVINO, Coral Edge TPU delegate, Raspberry Pi Camera Module `libcamera`).
- [ ] **Documentation & Sphinx Modernization**:
  - Refresh Sphinx configuration and generate clean HTML documentation.
  - Update `README.md` with architecture diagrams and quickstart examples.
