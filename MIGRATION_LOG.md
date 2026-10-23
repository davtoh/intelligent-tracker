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


