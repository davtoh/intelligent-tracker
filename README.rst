
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
- **Zero-Dependency Computer Vision Primitives**: Pure NumPy aspect-ratio preserving letterbox resizing, coordinate remapping, and vectorized multi-class Non-Maximum Suppression (NMS).
- **Hardware Acceleration Cascade**: Automatic runtime provider selection:
  ``CUDAExecutionProvider`` -> ``DmlExecutionProvider`` (DirectML on Windows) -> ``OpenVINOExecutionProvider`` (Intel) -> ``CoreMLExecutionProvider`` (macOS) -> ``CPUExecutionProvider``.
- **Pluggable Detector Interface**: Abstract ``BaseDetector`` contract returning typed ``Detection(bbox, class_id, confidence, label)`` namedtuples, decoupled by ``DetectorFactory``.
- **Flexible Video Ingestion**: USB webcams, IP camera RTSP streams, local video files, and headless synthetic mock feeds.
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

+---------------+---------------+--------------------------------------------------------------------------+
| Argument      | Default       | Description                                                              |
+===============+===============+==========================================================================+
| ``--detector``| ``haar``      | Detection architecture: ``yolov8``, ``yolo11``, ``haar``, ``mock``, etc. |
+---------------+---------------+--------------------------------------------------------------------------+
| ``--source``  | ``0``         | Camera index (``0``, ``1``), ``synthetic``, video file, or RTSP URL      |
+---------------+---------------+--------------------------------------------------------------------------+
| ``--resolution``| ``640x480`` | Frame resolution as ``WIDTHxHEIGHT``                                     |
+---------------+---------------+--------------------------------------------------------------------------+
| ``--framerate``| ``30``       | Target processing framerate (FPS)                                        |
+---------------+---------------+--------------------------------------------------------------------------+
| ``--conf``    | ``0.25``      | Detection confidence threshold (``0.0`` – ``1.0``)                       |
+---------------+---------------+--------------------------------------------------------------------------+
| ``--classes`` | ``None``      | Filter classes by name (``person``) or ID (``0``)                        |
+---------------+---------------+--------------------------------------------------------------------------+
| ``--headless``| ``False``     | Run without GUI (ideal for CI, servers, and benchmarks)                  |
+---------------+---------------+--------------------------------------------------------------------------+
| ``--frames``  | ``60``        | Frames to process in headless mode (``0`` = infinite)                    |
+---------------+---------------+--------------------------------------------------------------------------+

Running the Test Suite
----------------------

All unit tests run via Python's standard ``unittest`` discovery:

.. code-block:: powershell

    # Run full test suite (46 tests)
    $env:MPLBACKEND="Agg"
    .\.venv\Scripts\python.exe -m unittest discover tests

    # Run detector-specific unit tests (25 tests)
    .\.venv\Scripts\python.exe -m unittest tests/test_detectors.py

Roadmap & Status
----------------

- [x] **Milestone 1**: Environment & Core Engine Revitalization (Python 3.12, NumPy 2.x, cross-platform fixes).
- [x] **Milestone 2**: Edge AI Detection Architecture (YOLOv8/YOLO11 ONNX, BaseDetector, pure NumPy NMS).
- [ ] **Milestone 3**: RTSP Camera Streams & Retail / Occupancy Analytics (non-blocking reader, tripwires, heatmaps).
- [ ] **Milestone 4**: Event Dispatching & Alerting (Webhooks, Telegram bot, MQTT).
- [ ] **Milestone 5**: Web Dashboard, Packaging & Edge Deployment (FastAPI, Docker, systemd).

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

