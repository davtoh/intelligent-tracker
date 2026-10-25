
Intelligent Tracker — Edge AI Retail & Security Analytics Platform
==================================================================

.. image:: https://img.shields.io/pypi/v/intelligent-tracker.svg
   :target: https://pypi.org/project/intelligent-tracker/
   :alt: PyPI Version

.. image:: https://readthedocs.org/projects/intelligent-tracker/badge/?version=latest
   :target: https://intelligent-tracker.readthedocs.io/
   :alt: Documentation Status


Overview
--------

**Intelligent Tracker** is a modern, cross-platform Edge AI video analytics and tracking platform designed for smart cameras, retail occupancy monitoring, and security analytics.

Originally developed for Raspberry Pi and CCTV tracking using classical Haar cascades, the platform has been revitalized into a high-performance **Edge AI architecture** utilizing **ONNX Runtime** (YOLOv8, YOLO11) alongside legacy Haar cascades, color detection, and synthetic mock backends.

Key Capabilities
----------------

- **Edge AI Object Detection**: Native inference with **YOLOv8 Nano** and **YOLO11 Nano** via ONNX Runtime without heavy deep learning frameworks (no PyTorch/CUDA required on edge devices).
- **Multi-Object Tracking (MOT)**: High-speed ``CentroidTracker`` (IoU and Euclidean distance matching) and pure NumPy ``SortTracker`` (2D Kalman filtering).
- **Retail & Security Analytics**: Polygonal Zone ROIs for occupancy counting, dwell time monitoring, and bidirectional Virtual Tripwires for entry/exit traffic tallying.
- **Occupancy Heatmap Engine**: 2D spatial Gaussian density accumulation, continuous temporal decay, colormap overlays, and PNG/CSV exports.
- **Declarative YAML Configuration**: Template-driven setup (``configs/demo.yaml``, ``configs/retail.yaml``) for cameras, zones, tripwires, and models.
- **Non-blocking Threaded RTSP Reader**: Decoupled ingestion with automatic frame-drop on lag, auto-reconnection, and connection telemetry.
- **Zero-Dependency Computer Vision Primitives**: Pure NumPy aspect-ratio preserving letterbox resizing, coordinate remapping, and vectorized multi-class Non-Maximum Suppression (NMS).
- **Hardware Acceleration Cascade**: Automatic runtime provider selection:
  ``CUDAExecutionProvider`` -> ``DmlExecutionProvider`` (DirectML on Windows) -> ``OpenVINOExecutionProvider`` (Intel) -> ``CoreMLExecutionProvider`` (macOS) -> ``CPUExecutionProvider``.
- **Pluggable Detector Interface**: Abstract ``BaseDetector`` contract returning typed ``Detection(bbox, class_id, confidence, label)`` namedtuples, decoupled by ``DetectorFactory``.
- **Flexible Video Ingestion & Export**: USB webcams, IP camera RTSP streams, local video files, headless synthetic mock feeds, and annotated MP4 video recording.
- **Cross-Platform**: Tested and verified on Windows 10/11, Linux (Ubuntu, Debian, Raspberry Pi OS ARM64), and macOS (Apple Silicon & Intel).
- **Diagnostics & Tooling**: Built-in environment diagnostic tool (``scripts/diagnostics.py``) and model downloader with SHA-256 verification (``scripts/download_models.py``).

Latest Links:

- PyPI Package: https://pypi.org/project/intelligent-tracker/
- Documentation: https://intelligent-tracker.readthedocs.io/
- Project Homepage: https://github.com/davtoh/intelligent-tracker
- License: `GPL v3 Licence`_

Installation & Quickstart
-------------------------

Package Installation (PyPI)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

To install the distribution from PyPI:

.. code-block:: bash

    pip install intelligent-tracker

Prerequisites
~~~~~~~~~~~~~

- Python 3.10 – 3.12 (64-bit recommended). Python 3.12 is the primary development target.
- Modern virtual environment.

Setup on Windows (PowerShell)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: powershell

    # 1. Clone repository and navigate to root
    git clone https://github.com/davtoh/intelligent-tracker.git
    cd intelligent_tracker

    # 2. Create Python 3.12 virtual environment
    py -3.12 -m venv .venv

    # 3. Upgrade package managers and install dependencies
    .\.venv\Scripts\python.exe -m pip install -U pip setuptools wheel
    .\.venv\Scripts\pip.exe install -r requirements.txt

    # 4. Run system diagnostics
    .\.venv\Scripts\python.exe scripts/diagnostics.py

    # 5. Download pre-exported Edge AI models (YOLOv8 / YOLO11)
    .\.venv\Scripts\python.exe scripts/download_models.py --model yolov8n
    .\.venv\Scripts\python.exe scripts/download_models.py --model yolo11n

Setup on Linux / Raspberry Pi OS / macOS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # 1. Create and activate virtual environment
    python3 -m venv .venv
    source .venv/bin/activate

    # 2. Upgrade pip and install requirements
    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt

    # 3. Run diagnostics and download models
    python scripts/diagnostics.py
    python scripts/download_models.py --model yolov8n

Running the Application
-----------------------

Interactive GUI Tracking
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: powershell

    # Run YOLOv8 on default webcam
    .\.venv\Scripts\python.exe main.py --detector yolov8 --source 0

    # Run YOLO11 on synthetic test frames (no camera needed)
    .\.venv\Scripts\python.exe main.py --detector yolo11 --source synthetic

    # Filter for person detections with minimum confidence of 0.40
    .\.venv\Scripts\python.exe main.py --detector yolov8 --classes person --conf 0.40

    # Run with legacy Haar cascade face detector
    .\.venv\Scripts\python.exe main.py --detector haar --source 0

Headless Benchmarking (CI / Servers)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: powershell

    # Run 60 frames benchmark with YOLOv8 without opening GUI
    .\.venv\Scripts\python.exe main.py --detector yolov8 --source synthetic --headless --frames 60

CLI Options
~~~~~~~~~~~

+-----------------+---------------+--------------------------------------------------------------------------+
| Argument        | Default       | Description                                                              |
+=================+===============+==========================================================================+
| ``--config``    | ``None``      | Path to YAML/JSON configuration file (e.g. ``configs/demo.yaml``)        |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--detector``  | ``haar``      | Detection architecture: ``yolov8``, ``yolo11``, ``haar``, ``mock``, etc. |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--tracker``   | ``centroid``  | Multi-object tracker: ``centroid`` or ``sort`` (Kalman filter)           |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--source``    | ``0``         | Camera index, ``real`` (auto-detects physical webcam), ``synthetic``, etc|
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--gui``       | ``opencv``    | GUI backend: ``opencv`` (interactive HUD) or ``forms`` (Matplotlib)     |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--resolution``| ``640x480``   | Frame resolution as ``WIDTHxHEIGHT``                                     |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--framerate`` | ``30``        | Target processing framerate (FPS)                                        |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--conf``      | ``0.25``      | Detection confidence threshold (``0.0`` – ``1.0``)                       |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--classes``   | ``None``      | Filter classes by name (``person``) or ID (``0``)                        |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--heatmap``   | ``False``     | Enable spatial occupancy heatmap overlay                                 |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--output``    | ``None``      | Output path to save annotated video recording (``output.mp4``)           |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--db``        | ``data/...``  | Path to SQLite database file for Re-ID gallery and sightings             |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--reid``      | ``None``      | Visual Re-ID extractor: ``color``, ``onnx``, ``mock``, or ``none``       |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--reid-thresh``| ``0.65``     | Cosine similarity threshold for Re-ID gallery matching (``0.0`` – ``1.0``)|
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--headless``  | ``False``     | Run without GUI (ideal for CI, servers, and benchmarks)                  |
+-----------------+---------------+--------------------------------------------------------------------------+
| ``--frames``    | ``60``        | Frames to process in headless mode (``0`` = infinite)                    |
+-----------------+---------------+--------------------------------------------------------------------------+


Scenario Combinations Matrix
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| Scenario / Objective                | Detector   | Tracker    | Source            | Config File         | Key Parameters                                  | Mode                | Example Runnable Command                                                                           |
+=====================================+============+============+===================+=====================+=================================================+=====================+====================================================================================================+
| **Physical Webcam Auto-Detect**     | ``yolov8`` | ``centroid``| ``real``          | -                   | ``--classes person --conf 0.40``                | Interactive GUI     | ``python main.py --detector yolov8 --source real --classes person --conf 0.40``                     |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Synthetic CI Smoke Test**         | ``mock``   | ``centroid``| ``synthetic``    | ``configs/demo.yaml``| ``--headless --frames 30``                     | Headless (30f)      | ``python main.py --config configs/demo.yaml --headless --frames 30``                                |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **YOLOv8 Edge AI Benchmark**        | ``yolov8`` | ``centroid``| ``synthetic``    | ``configs/demo.yaml``| ``--detector yolov8 --headless --frames 60``     | Headless (60f)      | ``python main.py --config configs/demo.yaml --detector yolov8 --headless --frames 60``              |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **YOLO11 Performance Benchmark**    | ``yolo11`` | ``centroid``| ``synthetic``    | ``configs/demo.yaml``| ``--detector yolo11 --headless --frames 100``    | Headless (100f)     | ``python main.py --config configs/demo.yaml --detector yolo11 --headless --frames 100``             |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **SORT Kalman Tracking Test**       | ``mock``   | ``sort``   | ``synthetic``     | ``configs/demo.yaml``| ``--tracker sort --headless --frames 60``       | Headless (60f)      | ``python main.py --config configs/demo.yaml --tracker sort --headless --frames 60``                 |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Headless Video Export**           | ``yolov8`` | ``centroid``| ``synthetic``    | ``configs/demo.yaml``| ``--output recording.mp4 --headless --frames 90``| Headless Recording  | ``python main.py --config configs/demo.yaml --detector yolov8 --output recording.mp4 --headless --frames 90`` |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Retail Person Counting** (Webcam) | ``yolov8`` | ``centroid``| ``0``             | -                   | ``--classes person --conf 0.40``                | Interactive GUI     | ``python main.py --detector yolov8 --source 0 --classes person --conf 0.40``                        |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Store Foot-Traffic & Heatmap**    | ``yolov8`` | ``centroid``| ``real``          | ``configs/retail.yaml``| ``--heatmap``                                | Interactive GUI     | ``python main.py --config configs/retail.yaml --source real --heatmap``                             |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **RTSP IP Camera Surveillance**     | ``yolov8`` | ``centroid``| ``rtsp://...``    | ``configs/retail.yaml``| -                                            | Interactive / Stream| ``python main.py --config configs/retail.yaml --source rtsp://192.168.1.100/stream1``               |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Vehicle / Traffic Monitoring**    | ``yolov8`` | ``centroid``| ``traffic.mp4``   | -                   | ``--classes car truck bus --conf 0.50``         | Interactive GUI     | ``python main.py --detector yolov8 --source traffic.mp4 --classes car truck bus --conf 0.50``       |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Matplotlib Forms Toolbar GUI**    | ``yolov8`` | ``centroid``| ``synthetic``     | -                   | ``--gui forms``                                 | Matplotlib GUI      | ``python main.py --detector yolov8 --source synthetic --gui forms``                                 |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Legacy Face Tracking**            | ``face``   | ``centroid``| ``real``          | -                   | -                                               | Interactive GUI     | ``python main.py --detector face --source real``                                                     |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Color Blob / Marker Tracking**    | ``color``  | ``centroid``| ``real``          | -                   | -                                               | Interactive GUI     | ``python main.py --detector color --source real``                                                    |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Headless Remote Server / RPi**    | ``yolov8`` | ``centroid``| ``synthetic``     | ``configs/demo.yaml``| ``--headless --frames 120``                     | Headless Offscreen  | ``$env:MPLBACKEND="Agg"; python main.py --config configs/demo.yaml --detector yolov8 --headless --frames 120`` |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Visual Re-ID Person Gallery**     | ``yolov8`` | ``centroid``| ``real``          | ``configs/retail.yaml``| ``--reid onnx --db data/tracker.db``         | Interactive GUI     | ``python main.py --detector yolov8 --source real --reid onnx --db data/tracker.db``                 |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Interactive Tagging Studio**      | ``yolov8`` | ``centroid``| ``real``          | -                   | ``--reid color --db data/tracker.db``           | Tagging Studio      | ``python -m intelligent_tracker.interactive --source real --reid color --db data/tracker.db``        |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Offline Video Recording Indexer** | ``yolov8`` | ``centroid``| ``footage.mp4``   | -                   | ``--sample-rate 2 --report``                    | Offline Batch       | ``python -m intelligent_tracker.batch --video footage.mp4 --db data/tracker.db --report``           |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+
| **Event Dispatching & Alerting**    | ``mock``   | ``centroid``| ``synthetic``     | ``configs/alert_demo.yaml``| ``--headless --frames 30``               | Headless / Live     | ``python main.py --config configs/alert_demo.yaml --headless --frames 30``                          |
+-------------------------------------+------------+------------+-------------------+---------------------+-------------------------------------------------+---------------------+----------------------------------------------------------------------------------------------------+

Interactive GUI Controls
~~~~~~~~~~~~~~~~~~~~~~~~

- **Mouse Click**: Left-click on any tracked bounding box in the GUI window to inspect/select that entity and display real-time telemetry (ID, label, confidence, dwell time, velocity). Click in empty space to deselect.
- **Spacebar**: Pause / Resume video playback without losing tracking states.
- **``e``**: Enroll currently selected track into persistent SQLite Re-ID gallery with custom name, category, and notes.
- **``d``**: Clear / reset active tracks and deselect.
- **``h``**: Toggle live 2D spatial occupancy heatmap overlay.
- **``s``**: Save instantaneous snapshot image (``snapshot_<timestamp>.png``) and analytics report (``analytics_report_<timestamp>.json``).
- **``[X]`` Close Button / ``q`` / ``ESC``**: Gracefully exit application with highgui event flushing.


Running the Test Suite
----------------------

All unit tests run via Python's standard ``unittest`` discovery:

.. code-block:: powershell

    # Run full test suite (115 tests, 100% green)
    $env:MPLBACKEND="Agg"
    .\.venv\Scripts\python.exe -m unittest discover tests

    # Run Milestone 5 Event Dispatching & Alerting unit tests (18 tests)
    .\.venv\Scripts\python.exe -m tests.test_events

    # Run database, Re-ID, and batch indexing tests (27 tests)
    .\.venv\Scripts\python.exe -m unittest tests/test_database.py tests/test_reid.py tests/test_matcher.py tests/test_interactive.py tests/test_batch.py

    # Run detector-specific unit tests (25 tests)
    .\.venv\Scripts\python.exe -m unittest tests/test_detectors.py

    # Run video, tracker, and analytics unit tests (24 tests)
    .\.venv\Scripts\python.exe -m unittest tests/test_video.py tests/test_tracker.py tests/test_analytics.py

Roadmap & Status
----------------

- [x] **Milestone 1**: Environment & Core Engine Revitalization (Python 3.12, NumPy 2.x, cross-platform fixes).
- [x] **Milestone 2**: Edge AI Detection Architecture (YOLOv8/YOLO11 ONNX, BaseDetector, pure NumPy NMS).
- [x] **Milestone 3**: RTSP Camera Streams & Retail / Occupancy Analytics (non-blocking reader, tripwires, heatmaps).
- [x] **Milestone 4**: Object Identity Gallery, Visual Re-ID & Sighting Database (SQLite DB, ONNX OSNet, HSV fallback, interactive tagging, batch indexer).
- [x] **Milestone 5**: Event Dispatching & Alerting (Webhooks, Telegram bot, MQTT, quiet hours & rule engine).
- [ ] **Milestone 6**: Web Dashboard, Packaging & Edge Deployment (FastAPI, Docker, systemd).

See ``milestone_plan.md`` and ``TODO_MODERNIZATION.md`` for complete details.

Historical Showcase & Project Heritage
--------------------------------------

Intelligent Tracker was initially developed to bring automated tracking, keypoint analysis, and occupancy intelligence to edge hardware and CCTV systems using classical Haar cascades and adaptive contour models.

Below is an archive demonstration from the original tracking engine in action, illustrating object acquisition, trajectory vector calculation, contour hull smoothing, and boundary persistence across consecutive video frames:

.. figure:: https://github.com/davtoh/intelligent-tracker/blob/master/documentation/_static/Scene1_f1.jpg
    :align: center
    :scale: 25%
    :alt: Initial object acquisition and scene calibration (Frame 1)

.. figure:: https://github.com/davtoh/intelligent-tracker/blob/master/documentation/_static/Scene1_f2.jpg
    :align: center
    :scale: 25%
    :alt: Trajectory vector calculation and position history (Frame 2)

.. figure:: https://github.com/davtoh/intelligent-tracker/blob/master/documentation/_static/Scene1_f3.jpg
    :align: center
    :scale: 25%
    :alt: Centroid tracking and contour hull smoothing (Frame 3)

.. figure:: https://github.com/davtoh/intelligent-tracker/blob/master/documentation/_static/Scene1_f4.jpg
    :align: center
    :scale: 25%
    :alt: Multi-point tracking across scene space (Frame 4)

.. figure:: https://github.com/davtoh/intelligent-tracker/blob/master/documentation/_static/Scene1_f5.jpg
    :align: center
    :scale: 25%
    :alt: Persistent track state and boundary verification (Frame 5)

Contact & License
-----------------

- Author: David Toro
- E-mail: davsamirtor@gmail.com
- Project: https://github.com/davtoh/intelligent-tracker
- License: `GPL v3 Licence`_

.. _`GPL v3 Licence`: https://github.com/davtoh/intelligent-tracker/blob/master/LICENSE.rst
.. _`OpenCV linux installation`: https://github.com/davtoh/intelligent-tracker/blob/master/install_opencv.sh

