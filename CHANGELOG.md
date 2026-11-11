# Changelog

## [2026-11-11] feat: Video Pairing, Idempotent Transcode & Resolution-Aware Overlay (M1)
- **Type**: feat
- **Summary**: Added H.264 pair detection in /api/videos, idempotent /transcode with force flag, unified _h264/base report and detection storage, container PTS + source_resolution propagation in BatchAnalyzer and VideoReportStore, Switch/Re-convert library and codec notice UI controls, and letterbox/pillarbox-compensated source_resolution overlay scaling.
- **Files** (13):
  - `intelligent_tracker/batch.py`
  - `dashboard/services/video_transcoder.py`
  - `dashboard/services/video_report_store.py`
  - `dashboard/routers/videos.py`
  - `dashboard/routers/video_jobs.py`
  - `dashboard/static/js/scrubber_overlay.js`
  - `dashboard/static/js/video_jobs.js`
  - `dashboard/static/js/video_library.js`
  - ... (+5 more)
- **Verification**: unittest discover tests (344 OK); Milestone 1 suites (22 OK via plan_engine verify); sphinx -W --keep-going (0 warnings); headless diagnose.py ui audit OK

## [2026-11-10] feat: Video Studio SOTA Analytics, Canvas Overlay & Stacked Persistence Architecture
- **Type**: feat
- **Summary**: Implemented disk-backed stacked report history (`data/reports/{video}_reports.json`) and per-frame detection streaming (`data/reports/{video}_{run_id}_detections.json`). Separated raw detected objects (`total_detections`) from enrolled gallery sightings (`identifications_count`). Added synchronized real-time canvas bounding box overlay (`#scrubber-overlay-canvas`) over Scrubber player. Hardened `.video-file-card` selection, history run switcher dropdown, and active job container isolation.
- **Files** (8):
  - `intelligent_tracker/batch.py`
  - `dashboard/routers/video_jobs.py`
  - `dashboard/services/video_report_store.py`
  - `dashboard/static/js/scrubber_overlay.js`
  - `dashboard/static/js/video_batch.js`
  - `dashboard/static/js/video_library.js`
  - `dashboard/static/video_scrubber.js`
  - `tests/test_video_jobs.py`
- **Verification**: 337/337 tests pass (36.96s); 15/15 dedicated video jobs tests pass (1.09s); 0 warnings Sphinx HTML documentation build

## [2026-11-10] feat: Video Job Concurrency, Progress Engine & Interactive Cancellation (Milestone 17)
- **Type**: feat
- **Summary**: Implemented thread-safe VideoJobManager coordinator with BoundedSemaphore(2), per-video mutual exclusion, joinable cancellation, and job polling. Decoupled async job router into video_jobs.py. Added VideoJobClient frontend coordinator with animated progress bars, background task pills, and interactive 409 conflict modal. Added 12 unit and integration tests.
- **Files** (13):
  - `dashboard/routers/videos.py`
  - `dashboard/schemas.py`
  - `dashboard/services/video_jobs_service.py`
  - `dashboard/services/video_transcoder.py`
  - `dashboard/static/index.html`
  - `dashboard/static/js/video_batch.js`
  - `dashboard/static/js/video_jobs.js`
  - `dashboard/static/js/video_library.js`
  - ... (+5 more)
- **Verification**: 334/334 tests pass (37.2s); 12/12 dedicated video jobs tests pass (0.89s); 0 warnings Sphinx docs build

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
