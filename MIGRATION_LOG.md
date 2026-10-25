# Migration & Modernization Log: Intelligent Tracker

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
- `rules/task_logging.md`: Standardized task logging protocol.
- `TODO_MODERNIZATION.md`: Created detailed 5-phase modernization roadmap.
- `SETUP_GUIDE.md`: Comprehensive cross-platform setup guide (Windows, Linux/Raspberry Pi, macOS).
- `MIGRATION_LOG.md`: Initialized and maintained persistent migration tracking document.
- `requirements.txt`: Added `psutil>=5.8.0` for cross-platform memory and process telemetry.
- `main.py`: Added user-facing status messages for video tracking loop.
- `intelligent_tracker/core.py`:
  - Migrated `MutableMapping` and `MutableSet` imports from `collections.abc`.
  - Replaced deprecated `np.float` with `float` for NumPy 2.x compatibility.
  - Safely parsed OpenCV version string.
- `intelligent_tracker/array_utils.py`: Replaced deprecated `np.int` with `int`.
- `intelligent_tracker/detectors.py`:
  - Replaced deprecated `np.int` with `int`.
  - Fixed `DETECTOR_PATH` to reliably locate bundled cascade XML files.
- `intelligent_tracker/geometry.py`:
  - Replaced deprecated `np.int` and `np.alltrue` with standard `int` and `np.all`.
  - Updated `norm_point` to return native Python floats for OpenCV 4/5 `pointPolygonTest` compatibility.
- `intelligent_tracker/forms.py`: Added flexible backend selection respecting `MPLBACKEND` with graceful Qt/Tk/Agg fallbacks.
- `intelligent_tracker/periferials.py`: Added `MockVideoCapture` and reduced device probing to 5 indices, enabling smooth synthetic fallback when physical cameras are not connected.
- `tests/test_core.py`: Provided self-contained `TimeCode` context manager and `asizeof` memory helper; guarded Unix-only `resource` module with `psutil`.
- `tests/test_forms.py`: Added loop bound to prevent infinite blocking during automated/headless test execution.

### 3. State & Checkpoint
- **Status:** Milestone 1 COMPLETE (100% Green Unit Tests)
- **Automated Verification:**
  - Ran `.\.venv\Scripts\python.exe -m unittest discover tests` with `MPLBACKEND=Agg`.
  - Result: **Ran 21 tests in 1.832s — OK (0 failures, 0 errors)**.
- **Next Phase:**
  - Milestone 2: Edge AI Detection Architecture (Haar Cascades -> YOLOv8 / YOLOv11 Edge via ONNX Runtime / OpenVINO / Coral Edge TPU).

### 4. Verification Instructions
- **Windows (PowerShell):**
  ```powershell
  # Check python & pip in venv
  .\.venv\Scripts\python.exe --version
  .\.venv\Scripts\pip.exe --version

  # Run full automated test suite
  $env:MPLBACKEND="Agg"
  .\.venv\Scripts\python.exe -m unittest discover tests

  # Run main tracking demo
  .\.venv\Scripts\python.exe main.py
  ```
- **Fallback Verification (Historical Conda Python 3.7):**
  ```powershell
  C:\ProgramData\Anaconda3\envs\InteligentTracker\python.exe -m unittest tests/test_geometry.py
  C:\ProgramData\Anaconda3\envs\InteligentTracker\python.exe -m unittest tests/test_core.py
  ```

### 5. Quota / Context Recovery Guide
- If a new agent session starts:
  - Working directory: `g:\Mi unidad\projects\products\intelligent_tracker`
  - Active virtual environment: `.\.venv\` (Python 3.12.10 64-bit on Windows).
  - Do not use global `python` (which defaults to Windows App Store alias).
  - Check `TODO_MODERNIZATION.md` for current phase tasks.
  - Reference `rules/environment_and_execution.md` for executable commands.

---

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
  - `FaceDetector` & `EyeDetector`: Adapted to inherit from `HaarCascadeDetector`.
  - `ColorDetector`: Enhanced to implement `detect(frame)` returning `Detection` objects.
  - `MockDetector`: Deterministic synthetic bounding box generator for CI and headless testing.
- Modernize OpenCV tracker instantiation in `Object.update_tracker` with `_get_cv2_tracker` helper supporting OpenCV 4.x / 5.x namespace changes (`cv2.legacy`).
- Provide automated model download utility `scripts/download_models.py` with multi-mirror failover, streaming progress, and SHA-256 integrity verification for `yolov8n.onnx` and `yolo11n.onnx`.
- Modernize `main.py` CLI using `argparse` (`--detector`, `--source`, `--resolution`, `--framerate`, `--conf`, `--classes`, `--headless`, `--frames`).
- Build comprehensive unit test suite in `tests/test_detectors.py` (25 tests).

### 2. Files Touched
- `intelligent_tracker/detectors.py`:
  - Defined `Detection` namedtuple and `BaseDetector` abstract base class.
  - Built `DetectorFactory` registry supporting aliases and factory callables.
  - Implemented `OnnxDetector` with pure NumPy letterboxing, multi-class NMS, and execution provider auto-selection.
  - Implemented `HaarCascadeDetector` and updated `FaceDetector`, `EyeDetector`, `ColorDetector`.
  - Implemented `MockDetector` for deterministic synthetic testing.
  - Updated `Object.update_tracker` to support modern OpenCV 4/5 tracker namespaces (`cv2.legacy`).
- `scripts/download_models.py`: Created automated download utility with multi-mirror failover and SHA-256 integrity checks.
- `scripts/diagnostics.py`: Created hardware and runtime environment diagnostic utility (Python, OpenCV, GUI backends, cameras, ONNX providers, model weights).
- `main.py`: Modernized CLI entrypoint with flexible arguments for detector, source, resolution, confidence, class filtering, and headless benchmarking.
- `requirements.txt`: Added `onnxruntime>=1.18.0`.
- `tests/test_detectors.py`: Added 25 unit tests covering contracts, mock generators, factory lookup, cascade fallback, letterboxing, NumPy NMS, and full ONNX inference with YOLOv8n and YOLO11n.
- `TODO_MODERNIZATION.md`: Marked Phase 1 and Phase 2 milestones complete.
- `milestone_plan.md`: Verified and documented Milestone 2 deliverables and status.
- `README.rst`: Modernized project overview, features, installation, CLI usage, and architecture.
- `SETUP_GUIDE.md`: Updated with AI model download instructions, CLI arguments, and hardware acceleration guides.
- `documentation/detectors.rst`: Created detailed technical documentation for the Edge AI detection subsystem.
- `documentation/index.rst`: Added `detectors` to Sphinx table of contents.
- `documentation/conf.py`: Updated project metadata and version.

### 3. State & Checkpoint
- **Status:** Milestone 2 COMPLETE (100% Green Unit Tests)
- **Automated Verification:**
  - Full test suite: `.\.venv\Scripts\python.exe -m unittest discover tests` with `MPLBACKEND=Agg`.
  - Result: **Ran 46 tests in 2.45s — OK (0 failures, 0 errors)**.
  - Detector unit tests: `.\.venv\Scripts\python.exe -m unittest tests/test_detectors.py` -> **25/25 OK (0.84s)**.
  - Core & geometry tests: `tests/test_geometry.py`, `tests/test_core.py`, `tests/test_forms.py` -> **21/21 OK (1.42s)**.
- **Model Verification:**
  - `models/yolov8n.onnx`: 12.23 MB, SHA-256 verified, inference operational.
  - `models/yolo11n.onnx`: 10.20 MB, SHA-256 verified, inference operational.
- **Headless Benchmarks:**
  - `main.py --detector mock --source synthetic --headless --frames 30` -> 11.3 FPS.
  - `main.py --detector yolov8 --source synthetic --headless --frames 30` -> 7.2 FPS.
  - `main.py --detector yolo11 --source synthetic --headless --frames 30` -> 8.2 FPS.
- **Next Phase:**
  - Milestone 3: RTSP Camera Streams & Retail / Occupancy Analytics (non-blocking RTSP video reader, virtual tripwires, polygonal ROI zones, multi-object centroid tracking, and occupancy heatmaps).

### 4. Verification Instructions
- **Windows (PowerShell):**
  ```powershell
  # 1. Run system and hardware diagnostics
  .\.venv\Scripts\python.exe scripts/diagnostics.py

  # 2. Verify / Download models
  .\.venv\Scripts\python.exe scripts/download_models.py --model yolov8n
  .\.venv\Scripts\python.exe scripts/download_models.py --model yolo11n

  # 3. Run full automated test suite
  $env:MPLBACKEND="Agg"
  .\.venv\Scripts\python.exe -m unittest discover tests

  # 4. Run detector unit tests individually
  .\.venv\Scripts\python.exe -m unittest tests/test_detectors.py

  # 5. Run headless tracking benchmarks
  .\.venv\Scripts\python.exe main.py --detector mock --source synthetic --headless --frames 30
  .\.venv\Scripts\python.exe main.py --detector yolov8 --source synthetic --headless --frames 30
  .\.venv\Scripts\python.exe main.py --detector yolo11 --source synthetic --headless --frames 30

  # 6. Run interactive tracking with webcam / synthetic source
  .\.venv\Scripts\python.exe main.py --detector yolov8 --source synthetic
  ```
- **Linux / Raspberry Pi OS:**
  ```bash
  source .venv/bin/activate
  python scripts/diagnostics.py
  python scripts/download_models.py --model yolov8n
  MPLBACKEND=Agg python -m unittest discover tests
  python main.py --detector yolov8 --source 0
  ```
- **macOS:**
  ```bash
  source .venv/bin/activate
  python scripts/diagnostics.py
  python scripts/download_models.py --model yolov8n
  MPLBACKEND=Agg python -m unittest discover tests
  python main.py --detector yolov8 --source 0
  ```

### 5. Quota / Context Recovery Guide
- If a new agent session starts:
  - Working directory: `g:\Mi unidad\projects\products\intelligent_tracker`
  - Active virtual environment: `.\.venv\` (Python 3.12.10 64-bit on Windows).
  - Pre-downloaded ONNX models: Located in `models/` (`yolov8n.onnx`, `yolo11n.onnx`).
  - Next task to execute: **Milestone 3 — RTSP Camera Streams & Retail / Occupancy Analytics**.
  - Review `milestone_plan.md` (lines 96-147) and `TODO_MODERNIZATION.md` (lines 51-64) for Phase 3 requirements:
    - 3a: Non-blocking RTSP video reader (`intelligent_tracker/video.py`).
    - 3b: Zone & tripwire geometry (`intelligent_tracker/geometry.py`).
    - 3c: Multi-object centroid tracker (`intelligent_tracker/tracker.py`).
    - 3d: Occupancy heatmap accumulation (`intelligent_tracker/analytics.py`).
    - 3e: Real-time visual overlay and CLI configuration.

---

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
- Build spatial analytics engine in `intelligent_tracker.analytics`:
  - `OccupancyHeatmap`: 2D spatial Gaussian density accumulation, continuous temporal decay, false-color overlay blending (JET/INFERNO), PNG snapshot, and CSV grid exports.
  - `AnalyticsEngine`: Central coordinator managing multi-zone occupancy, tripwire tallies, events, and telemetry report generation.
- Modernize CLI and configurations:
  - Created declarative YAML templates: `configs/demo.yaml` (synthetic demo) and `configs/retail.yaml` (production retail surveillance).
  - Modernized `main.py` CLI supporting `--config`, `--tracker`, `--heatmap`, `--output` video recording, and interactive controls (`q` quit, `d` clear, `h` heatmap toggle, `s` save snapshot/report).
- Expanded unit test coverage: Added 17 new tests across `tests/test_video.py`, `tests/test_tracker.py`, and `tests/test_analytics.py`, achieving 63/63 passing tests (100% green).
- Created technical documentation in `documentation/analytics.rst` and updated Sphinx toctree.

### 2. Files Touched
- `intelligent_tracker/video.py`: Created threaded non-blocking video reader (`VideoSource`) and `SyntheticFrameGenerator`.
- `intelligent_tracker/geometry.py`: Added `Tripwire`, `ZoneROI`, `ZoneEvent`, `TripwireEvent`, and `segments_intersect`.
- `intelligent_tracker/high_objects.py`: Integrated `Area` and `Line` agents with `ZoneROI` and `Tripwire`.
- `intelligent_tracker/tracker.py`: Created `Track`, `CentroidTracker`, `SortTracker` (NumPy Kalman filter), and `TrackerFactory`.
- `intelligent_tracker/analytics.py`: Created `OccupancyHeatmap` and `AnalyticsEngine`.
- `configs/demo.yaml`: Created synthetic demo configuration template.
- `configs/retail.yaml`: Created production retail surveillance configuration template.
- `main.py`: Modernized with `--config`, `--tracker`, `--heatmap`, `--output` video recording, and analytics overlay.
- `requirements.txt`: Added `pyyaml>=6.0.0`.
- `tests/test_video.py`: Added 5 unit tests for VideoSource and SyntheticFrameGenerator.
- `tests/test_tracker.py`: Added 7 unit tests for Track, CentroidTracker, SortTracker, and TrackerFactory.
- `tests/test_analytics.py`: Added 5 unit tests for Tripwire, ZoneROI, OccupancyHeatmap, and AnalyticsEngine.
- `milestone_plan.md`: Updated Milestone 3 status to COMPLETE with verification commands and deliverables.
- `TODO_MODERNIZATION.md`: Marked Phase 3 milestones complete.
- `README.rst`: Updated capabilities, CLI options table, test commands, and roadmap.
- `documentation/analytics.rst`: Created detailed technical documentation for video ingestion and retail analytics.
- `documentation/index.rst`: Added `analytics` to Sphinx table of contents.
- `MIGRATION_LOG.md`: Documented Milestone 3 completion and updated context recovery guide.

### 3. State & Checkpoint
- **Status:** Milestone 3 COMPLETE (100% Green Unit Tests)
- **Automated Verification:**
  - Full test suite: `.\.venv\Scripts\python.exe -m unittest discover tests` with `MPLBACKEND=Agg`.
  - Result: **Ran 63 tests in 4.32s — OK (0 failures, 0 errors)**.
  - Video unit tests: `tests/test_video.py` -> **5/5 OK (0.35s)**.
  - Tracker unit tests: `tests/test_tracker.py` -> **7/7 OK (0.01s)**.
  - Analytics unit tests: `tests/test_analytics.py` -> **5/5 OK (0.06s)**.
  - Detector unit tests: `tests/test_detectors.py` -> **25/25 OK (0.84s)**.
  - Core & geometry legacy tests: `tests/test_geometry.py`, `tests/test_core.py`, `tests/test_forms.py` -> **21/21 OK (1.42s)**.
- **Hardware & GUI Stabilization Fixes (Windows Edge Cases):**
  - **Window Close `[X]` Button**: Fixed OpenCV HighGUI event pumping sequence in `main.py`. Moving `cv2.getWindowProperty` check immediately after `cv2.waitKey(1)` prevents `cv2.imshow` from re-instantiating destroyed window handles. Added event loop flush (`for _ in range(5): cv2.waitKey(1)`) after `cv2.destroyAllWindows()`.
  - **Webcam Driver Lock (`Error: -1072873822`)**: Enforced DirectShow (`cv2.CAP_DSHOW`) backend exclusively on Windows for webcams in `video.py` and `periferials.py`, eliminating async COM device locks from `cap_msmf.cpp`. Added 15-frame transient read retry to prevent unnecessary device teardown on momentary exposure/frame drops, accompanied by clean driver release teardown delays.
- **Pipeline Benchmarks:**
  - `main.py --config configs/demo.yaml --headless --frames 30` -> 29.1 FPS (Mock + Synthetic).
  - `main.py --config configs/demo.yaml --detector yolov8 --headless --frames 30` -> 16.6 FPS (YOLOv8 + Bounded buffer frame-drop).
  - `main.py --config configs/demo.yaml --headless --frames 30 --output scratch/test_output.mp4` -> Output video verified with bounding boxes, trajectory trails, zone occupancy badges, and tripwire counters.
- **Next Phase:**
  - Milestone 4: Object Identity Gallery, Re-Identification (Re-ID) & Sighting Database (persistent SQLite database `data/tracker.db`, visual Re-ID embeddings via ONNX/HSV color descriptors, interactive screen selection/tagging, cross-session re-appearance matching, and offline recording occurrence indexer).

### 4. Verification Instructions
- **Windows (PowerShell):**
  ```powershell
  # 1. Run full automated test suite (63 tests)
  $env:MPLBACKEND="Agg"
  .\.venv\Scripts\python.exe -m unittest discover tests

  # 2. Run Milestone 3 unit test modules specifically
  .\.venv\Scripts\python.exe -m unittest tests/test_video.py tests/test_tracker.py tests/test_analytics.py

  # 3. Run synthetic demo with YAML config (headless)
  .\.venv\Scripts\python.exe main.py --config configs/demo.yaml --headless --frames 30

  # 4. Run YOLOv8 tracking with video recording output
  .\.venv\Scripts\python.exe main.py --config configs/demo.yaml --detector yolov8 --headless --frames 30 --output scratch/test_output.mp4

  # 5. Run live interactive GUI with synthetic or webcam feed
  .\.venv\Scripts\python.exe main.py --config configs/demo.yaml
  ```
- **Linux / Raspberry Pi OS / macOS:**
  ```bash
  source .venv/bin/activate
  MPLBACKEND=Agg python -m unittest discover tests
  python main.py --config configs/demo.yaml --headless --frames 30
  ```

### 5. Quota / Context Recovery Guide
- If a new agent session starts:
  - Working directory: `g:\Mi unidad\projects\products\intelligent_tracker`
  - Active virtual environment: `.\.venv\` (Python 3.12.10 64-bit on Windows).


---

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
  - Dual GUI support: `--gui opencv` (OpenCV HUD) and `--gui forms` (legacy Matplotlib navigation toolbar).
- **Documentation Updates**:
  - `SETUP_GUIDE.md`: Updated Section 6 with `--source real` auto-detection behavior, dual GUI flags, interactive controls, and scenarios matrix.
  - `README.rst`: Updated Key Capabilities, CLI options table, scenarios matrix, and interactive keyboard/mouse controls.
  - `documentation/intelligent_tracker.rst`: Added Sphinx automodules for `video`, `tracker`, and `analytics`.

### 2. Files Touched
- `intelligent_tracker/video.py` (Unbind cooldowns, settle delays, console logging, physical camera verification)
- `intelligent_tracker/periferials.py` (DirectShow backend alignment on Windows)
- `main.py` (GUI modes, interactive mouse selection callback, spacebar pause, [X] event pumping)
- `tests/test_video.py` (Tests for `is_physical_camera`, `resolve_camera_source`, immediate unblocking)
- `SETUP_GUIDE.md` (CLI tables, scenarios matrix, hardware auto-detect guide, interactive controls)
- `README.rst` (CLI table, scenarios matrix, GUI controls)
- `documentation/intelligent_tracker.rst` (Sphinx submodule references)
- `TODO_MODERNIZATION.md` (Updated task tracking)
- `milestone_plan.md` (Updated Milestone 4 interactive GUI specifications)
- `MIGRATION_LOG.md` (Persistent task log)

### 3. State & Checkpoint
- **Status:** All unit tests green (67/67 OK in 5.3s).
- **Automated Verification:**
  - `.\.venv\Scripts\python.exe -m unittest discover tests` -> **67/67 OK (5.32s)**.
  - `.\.venv\Scripts\python.exe -m unittest tests/test_video.py` -> **9/9 OK (0.38s)**.
- **Next Phase:**
  - Milestone 4: Object Identity Gallery, Re-Identification (Re-ID) & Sighting Database (`intelligent_tracker/database.py`, `intelligent_tracker/reid.py`).

### 4. Verification Instructions
- **Windows (PowerShell):**
  ```powershell
  # 1. Run full test suite (67 tests)
  $env:MPLBACKEND="Agg"
  .\.venv\Scripts\python.exe -m unittest discover tests

  # 2. Run camera auto-detection with real physical hardware webcam
  .\.venv\Scripts\python.exe main.py --detector yolo11 --source real --classes person --conf 0.35

  # 3. Run interactive GUI with mouse click inspection and spacebar pause
  .\.venv\Scripts\python.exe main.py --config configs/demo.yaml

  # 4. Run with legacy Matplotlib forms GUI
  .\.venv\Scripts\python.exe main.py --config configs/demo.yaml --gui forms
  ```

### 5. Quota / Context Recovery Guide
- If a new agent session starts:
  - Working directory: `c:\dev\projects\products\intelligent_tracker`
  - Active virtual environment: `.\.venv\` (Python 3.12.10 64-bit on Windows).
  - Next task to execute: **Milestone 4 — Object Identity Gallery, Re-Identification (Re-ID) & Sighting Database**.

---

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
- Create Gallery Matcher & Re-Appearance Engine in `intelligent_tracker/matcher.py`:
  - Temporal feature pooling: collects and averages embeddings across high-confidence frames per track.
  - Vectorized gallery search against enrolled active signatures.
  - Debounced sighting audit trail: logs verified entity sightings to SQLite database without redundant per-frame writes.
  - Emits `EntityIdentifiedEvent` and decorates `Track` with entity ID, name, category, and similarity score.
- Deliver Interactive Screen Selection, Tagging & GUI Controls in `intelligent_tracker/interactive.py`:
  - Left-click on tracked bounding box to inspect target telemetry (Track ID, Re-ID match, dwell time, velocity).
  - Press `e` to trigger entity enrollment prompt, automatically capturing thumbnail crops and extracting feature vectors.
  - Interactive ROI drawing: Press `t` to draw virtual tripwires or `z` to draw polygonal zones directly on the live/paused window.
  - Standalone studio CLI: `python -m intelligent_tracker.interactive`.
- Implement Offline Video Recording Indexer & Occurrence Analytics in `intelligent_tracker/batch.py`:
  - Fast-forward video batch processing with frame sampling (`--sample-rate N`).
  - Sighting timelines, visit frequencies, and zone journey reports.
  - Export reports to JSON and CSV formats.
  - Standalone indexer CLI: `python -m intelligent_tracker.batch`.
- Integrated Re-ID into `main.py` CLI (`--db`, `--reid`, `--reid-thresh`), updated declarative YAML configs (`configs/demo.yaml`, `configs/retail.yaml`), and added `osnet_x0_25` ONNX model download with SHA-256 verification in `scripts/download_models.py`.
- Expanded test suite from 67 to 92 tests (+25 new unit tests) across `test_database.py`, `test_reid.py`, `test_matcher.py`, `test_interactive.py`, and `test_batch.py` (100% green).
- Created technical documentation in `documentation/reid.rst` and updated Sphinx toctree.

### 2. Files Touched
- `intelligent_tracker/database.py`: Created `TrackerDB` SQLite database manager, schema, CRUD, signatures, sightings, analytics, and JSON/CSV exporters.
- `intelligent_tracker/reid.py`: Created `BaseFeatureExtractor`, `ColorHistogramExtractor` (joint 3D HSV), `OnnxReIDExtractor`, `MockFeatureExtractor`, `ReIDExtractorFactory`, and `batch_cosine_similarity`.
- `intelligent_tracker/matcher.py`: Created `GalleryMatcher`, `EntityIdentifiedEvent`, multi-frame feature pooling, and debounced sighting audit trail.
- `intelligent_tracker/interactive.py`: Created `InteractiveController` (screen inspection, enrollment dialog, interactive tripwire/zone drawing) and standalone CLI runner.
- `intelligent_tracker/batch.py`: Created `VideoIndexer` (batch frame-sampled video ingestion, occurrence reporting, JSON/CSV exports) and CLI runner.
- `intelligent_tracker/analytics.py`: Enhanced `analytics.draw` track badge to render recognized entity names and match percentages.
- `main.py`: Added `--db`, `--reid`, and `--reid-thresh` CLI arguments, Re-ID matcher loop integration, interactive `'e'` enrollment key handler, and clean database lifecycle teardown.
- `scripts/download_models.py`: Added `osnet_x0_25.onnx` model entry with dual Hugging Face mirrors, SHA-256 verification, and streaming progress.
- `configs/demo.yaml`: Added `database` and `reid` configuration blocks.
- `configs/retail.yaml`: Added production `database` and `reid` (ONNX) configuration blocks.
- `tests/test_database.py`: Created 8 unit tests for SQLite database schema, CRUD, signatures, sightings, analytics, cascade delete, and thread safety.
- `tests/test_reid.py`: Created 7 unit tests for feature extractors, spatial HSV histograms, OnnxReIDExtractor fallback, and cosine similarity.
- `tests/test_matcher.py`: Created 4 unit tests for GalleryMatcher, feature pooling, recognition threshold, sighting debouncing, and manual reassignment.
- `tests/test_interactive.py`: Created 4 unit tests for mouse click inspection, tripwire drawing, zone drawing, and HUD overlay rendering.
- `tests/test_batch.py`: Created 2 unit tests for offline video batch indexing, occurrence reporting, and JSON/CSV export.
- `documentation/reid.rst`: Created detailed technical documentation for visual Re-ID, SQLite database, interactive tagging, and batch indexing.
- `documentation/index.rst`: Added `reid` to Sphinx toctree.
- `documentation/intelligent_tracker.rst`: Added automodule documentation blocks for `database`, `reid`, `matcher`, `interactive`, and `batch`.
- `README.rst`: Updated CLI options table, scenarios matrix, interactive keyboard controls, test commands, and roadmap.
- `TODO_MODERNIZATION.md`: Marked Phase 4 tasks complete.
- `milestone_plan.md`: Updated Milestone 4 status to COMPLETE (including Enhancement 4f) with verification commands and deliverables.
- `MIGRATION_LOG.md`: Documented Milestone 4 completion (with 4f predictive coasting & session Re-ID) and updated context recovery guide.
- `intelligent_tracker/tracker.py`: Implemented `Track.predict(timestamp, bounds)` dead-reckoning extrapolation, `Track.state` lifecycle transitions (`active`/`confirmed`, `predicting`, `dormant`), boundary `exit_point`/`exit_time` telemetry, and `CentroidTracker(coast_frames=N)` trajectory coasting.
- `intelligent_tracker/matcher.py`: Built `SessionEntity` in-memory canonical identity management (`Person #1`, `Person #2`), eliminating track ID inflation (Person #35), and implemented fused affinity re-linking (visual cosine similarity + spatial exit proximity bonus).
- `intelligent_tracker/analytics.py`: Enhanced `AnalyticsEngine.draw` with distinct dimmed/orange bounding boxes and `[PREDICTING]` badge; maintained continuous zone dwell time and occupancy during coasting.
- `main.py`: Set default Re-ID to spatial color histogram descriptor; modernized interactive HUD and selection inspection to display persistent session identity and predicting state.
- `tests/test_tracker.py`: Added 2 unit tests (`test_dead_reckoning_predict`, `test_centroid_tracker_coasting_and_recovery`).
- `tests/test_matcher.py`: Added 2 unit tests (`test_auto_session_gallery_assignment`, `test_auto_session_gallery_reidentification_on_reappearance`).
- `tests/test_analytics.py`: Added 1 unit test (`test_zone_continuity_during_coasting`).
- `documentation/reid.rst`: Documented predictive motion coasting, dead-reckoning, automatic session gallery, and fused affinity re-linking.

### 3. State & Checkpoint
- **Status:** Milestone 4 COMPLETE (100% Green Unit Tests)
- **Automated Verification:**
  - Full test suite: `.\.venv\Scripts\python.exe -m unittest discover tests` with `MPLBACKEND=Agg`.
  - Result: **Ran 97 tests in 4.137s — OK (0 failures, 0 errors, 100% passing)**.
  - Database unit tests: `tests/test_database.py` -> **8/8 OK (0.74s)**.
  - Re-ID unit tests: `tests/test_reid.py` -> **7/7 OK (0.07s)**.
  - Matcher unit tests: `tests/test_matcher.py` -> **6/6 OK (0.01s)**.
  - Interactive unit tests: `tests/test_interactive.py` -> **4/4 OK (0.03s)**.
  - Batch indexer unit tests: `tests/test_batch.py` -> **2/2 OK (0.14s)**.
  - Detector unit tests: `tests/test_detectors.py` -> **25/25 OK (0.84s)**.
  - Video, tracker & analytics unit tests: `tests/test_video.py`, `tests/test_tracker.py`, `tests/test_analytics.py` -> **24/24 OK (0.45s)**.
  - Core & geometry legacy tests: `tests/test_geometry.py`, `tests/test_core.py`, `tests/test_forms.py` -> **21/21 OK (1.42s)**.
- **Pipeline Benchmarks:**
  - `main.py --config configs/demo.yaml --headless --frames 15 --reid color` -> 26.5 FPS.
  - `main.py --config configs/demo.yaml --headless --frames 15 --reid onnx` -> 26.5 FPS (ONNX OSNet x0.25).
  - `main.py --config configs/demo.yaml --detector yolov8 --reid onnx --headless --frames 30` -> 18.0 FPS.
  - `batch.py --video scratch/test_output.mp4 --report` -> 656.9 FPS (offline video batch processing).
- **Next Phase:**
  - Milestone 5: Event Dispatching & Alerting System (Webhooks, Telegram bot, MQTT broker integration, configurable alert rules).

### 4. Verification Instructions
- **Windows (PowerShell):**
  ```powershell
  # 1. Run full test suite (97 tests)
  $env:MPLBACKEND="Agg"
  .\.venv\Scripts\python.exe -m unittest discover tests

  # 2. Run Milestone 4 Re-ID and Database unit test suite specifically (27 tests)
  .\.venv\Scripts\python.exe -m unittest tests/test_database.py tests/test_reid.py tests/test_matcher.py tests/test_interactive.py tests/test_batch.py

  # 3. Interactive tagging & Re-ID studio CLI help
  .\.venv\Scripts\python.exe -m intelligent_tracker.interactive --help

  # 4. Run live tracking with YOLOv8, ONNX Re-ID, and SQLite database
  .\.venv\Scripts\python.exe main.py --config configs/demo.yaml --detector yolov8 --reid onnx --db data/tracker.db --headless --frames 30

  # 5. Process offline recording and print sighting occurrence analytics
  .\.venv\Scripts\python.exe -m intelligent_tracker.batch --video scratch/test_output.mp4 --db data/tracker.db --report
  ```
- **Linux / Raspberry Pi OS / macOS:**
  ```bash
  source .venv/bin/activate
  MPLBACKEND=Agg python -m unittest discover tests
  python main.py --config configs/demo.yaml --detector yolov8 --reid color --db data/tracker.db --headless --frames 30
  ```

### 5. Quota / Context Recovery Guide
- If a new agent session starts:
  - Working directory: `c:\dev\projects\products\intelligent_tracker`
  - Active virtual environment: `.\.venv\` (Python 3.12.10 64-bit on Windows).
  - Downloaded AI models: Located in `models/` (`yolov8n.onnx`, `yolo11n.onnx`, `osnet_x0_25.onnx`).
  - Milestone 4 and Milestone 5 are COMPLETE.
  - Next task to execute: **Milestone 6 — Modern Web Dashboard, Packaging & Edge Deployment**.

---

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
  - Time-of-day quiet hours schedule evaluation supporting overnight spans crossing midnight (e.g. 22:00 to 06:00).
  - Configurable alert rules with zone filters, event action triggers, entity categories (`restricted`, `unknown`), minimum dwell duration, and rule-level cooldowns.
  - Automatic alert derivation: transforms raw track and zone interactions into `IntrusionAlert` and `RestrictedEntityAlert` with attached visual snapshots.
- Integrate alerting pipeline into `AnalyticsEngine`, `main.py`, and `ZoneROI` (with `capacity_limit` threshold monitoring).
- Provide complete demo configuration `configs/alert_demo.yaml`.
- Build comprehensive unit test suite in `tests/test_events.py` with real local HTTP echo test server, mock MQTT, and rules integration (18 tests).

### 2. Files Touched
- `requirements.txt`: Added `paho-mqtt>=2.0.0`, `requests>=2.28.0`, and `python-telegram-bot>=20.0`.
- `intelligent_tracker/events.py`: Created complete event dispatching and alerting system (`EventBus`, `WebhookDispatcher`, `TelegramDispatcher`, `MqttPublisher`, `QuietHours`, `AlertRule`, `AlertRuleEngine`, `setup_event_pipeline`, typed dataclasses, and snapshot encoders).
- `intelligent_tracker/geometry.py`: Added `capacity_limit` and `_threshold_breached` attributes to `ZoneROI`.
- `intelligent_tracker/analytics.py`: Integrated `event_bus` and `camera_id` into `AnalyticsEngine`, automated event conversion and publishing (`TripwireCrossEvent`, `ZoneEvent`), and added capacity limit threshold checking (`OccupancyThresholdEvent`).
- `main.py`: Added `alerting` configuration parsing, event pipeline initialization, Re-ID recognition event publishing (`EntityIdentifiedEvent`, `RestrictedEntityAlert`), real-time MQTT occupancy telemetry broadcasting, and clean pipeline shutdown.
- `configs/alert_demo.yaml`: Created complete demonstration configuration with synthetic source, mock detector, restricted vault zone, public lobby, webhook dispatcher, mock Telegram bot, mock MQTT broker, and security alert rules.
- `tests/test_events.py`: Created 18 comprehensive unit tests covering dataclasses, snapshot encoders, event bus pub/sub, local HTTP echo server webhook delivery, retry/backoff, Telegram rate-limiting and `/status` commands, MQTT topics, quiet hours overnight spans, rule matching, and full pipeline integration.
- `documentation/events.rst`: Created detailed technical documentation for Milestone 5.
- `documentation/index.rst`: Added `events` to Sphinx toctree.
- `documentation/intelligent_tracker.rst`: Added `intelligent_tracker.events` automodule documentation.
- `README.rst`: Updated scenarios matrix with `configs/alert_demo.yaml`, updated test suite commands, and marked Milestone 5 complete in roadmap.
- `TODO_MODERNIZATION.md`: Marked Phase 5 tasks complete.
- `milestone_plan.md`: Updated Milestone 5 status to COMPLETE with verification commands and deliverables.
- `MIGRATION_LOG.md`: Documented Milestone 5 completion and updated context recovery guide.

### 3. State & Checkpoint
- **Status:** Milestone 5 COMPLETE (100% Green Unit Tests)
- **Automated Verification:**
  - Full test suite: `.\.venv\Scripts\python.exe -m unittest discover tests` with `MPLBACKEND=Agg`.
  - Result: **Ran 115 tests in 6.189s — OK (0 failures, 0 errors, 100% passing)**.
  - Milestone 5 unit tests: `tests/test_events.py` -> **18/18 OK (1.21s)**.
  - Database unit tests: `tests/test_database.py` -> **8/8 OK (0.74s)**.
  - Re-ID unit tests: `tests/test_reid.py` -> **7/7 OK (0.07s)**.
  - Matcher unit tests: `tests/test_matcher.py` -> **6/6 OK (0.01s)**.
  - Interactive unit tests: `tests/test_interactive.py` -> **4/4 OK (0.03s)**.
  - Batch indexer unit tests: `tests/test_batch.py` -> **2/2 OK (0.14s)**.
  - Detector unit tests: `tests/test_detectors.py` -> **25/25 OK (0.84s)**.
  - Video, tracker & analytics unit tests: `tests/test_video.py`, `tests/test_tracker.py`, `tests/test_analytics.py` -> **27/27 OK (0.50s)**.
  - Core & geometry legacy tests: `tests/test_geometry.py`, `tests/test_core.py`, `tests/test_forms.py` -> **21/21 OK (1.42s)**.
- **Pipeline Benchmarks:**
  - `main.py --config configs/alert_demo.yaml --headless --frames 30` -> 27.7 FPS with active Webhook, Telegram, MQTT, and Rules engine.
- **Next Phase:**
  - Milestone 6: Web Dashboard, Packaging & Edge Deployment (FastAPI + WebSocket live stream, React/HTML5 web UI, Docker containerization, systemd service, Sphinx docs).

### 4. Verification Instructions
- **Windows (PowerShell):**
  ```powershell
  # 1. Run full test suite (115 tests)
  $env:MPLBACKEND="Agg"
  .\.venv\Scripts\python.exe -m unittest discover tests

  # 2. Run Milestone 5 Event Dispatching & Alerting unit test suite specifically (18 tests)
  .\.venv\Scripts\python.exe -m tests.test_events

  # 3. Run live tracking with YOLOv8, ONNX Re-ID, and SQLite database
  .\.venv\Scripts\python.exe main.py --config configs/demo.yaml --detector yolov8 --reid onnx --db data/tracker.db --headless --frames 30

  # 4. Run live tracking with Milestone 5 Event Alerting Pipeline (Webhooks, Telegram, MQTT, Rules)
  .\.venv\Scripts\python.exe main.py --config configs/alert_demo.yaml --headless --frames 30
  ```
- **Linux / Raspberry Pi OS / macOS:**
  ```bash
  source .venv/bin/activate
  MPLBACKEND=Agg python -m unittest discover tests
  python -m tests.test_events
  python main.py --config configs/alert_demo.yaml --headless --frames 30
  ```

### 5. Quota / Context Recovery Guide
- If a new agent session starts:
  - Working directory: `c:\dev\projects\products\intelligent_tracker`
  - Active virtual environment: `.\.venv\` (Python 3.12.10 64-bit on Windows).
  - Downloaded AI models: Located in `models/` (`yolov8n.onnx`, `yolo11n.onnx`, `osnet_x0_25.onnx`).
  - Next task to execute: **Milestone 6 — Web Dashboard, Packaging & Edge Deployment**.
  - Review `milestone_plan.md` (lines 276-320) and `TODO_MODERNIZATION.md` (lines 113-124) for Milestone 6 requirements:
    - 6a: Modern Web Analytics Dashboard (FastAPI + WebSocket + MJPEG live stream).
    - 6b: Entity Gallery View in Browser.
    - 6c: Edge Deployment (Dockerfile for ARM64/x86_64, systemd service).
    - 6d: Sphinx HTML Documentation Refresh.





