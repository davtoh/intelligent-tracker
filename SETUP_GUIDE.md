# Intelligent Tracker: Cross-Platform Setup & Modernization Guide

This guide details how to configure, run, and develop **Intelligent Tracker** on **Windows**, **Linux (including Raspberry Pi OS)**, and **macOS**.

---

## 1. System Requirements & Prerequisites

| Operating System | Recommended Python | Key System Dependencies |
| :--- | :--- | :--- |
| **Windows 10 / 11** | Python 3.10 – 3.12 (64-bit) | Microsoft Visual C++ Redistributable 2015–2022 |
| **Linux (Ubuntu / Debian)** | Python 3.10 – 3.12 | `python3-venv`, `python3-pip`, `libgl1`, `libglib2.0-0` |
| **Raspberry Pi OS (Bookworm/Bullseye)**| Python 3.10 – 3.12 (ARM64) | `v4l-utils`, `libcamera`, `libgl1` |
| **macOS (Apple Silicon & Intel)** | Python 3.10 – 3.12 | Homebrew, Xcode Command Line Tools |

> [!NOTE]
> Avoid Python 3.14 for computer vision dependencies until binary wheels are mature on PyPI. Python 3.12 is the recommended target.

---

## 2. Setup on Windows (Current Environment)

### Step 2.1: Open PowerShell or Command Prompt
Navigate to the project root:
```powershell
cd "G:\Mi unidad\projects\products\intelligent_tracker"
```

### Step 2.2: Create and Activate Virtual Environment
Use the Python 3.12 launcher (`py -3.12`):
```powershell
# Create the virtual environment
py -3.12 -m venv .venv

# Upgrade pip, setuptools, and wheel
.\.venv\Scripts\python.exe -m pip install -U pip setuptools wheel
```

> [!WARNING]
> Do **not** use the bare system command `python` if Windows redirects to the Microsoft Store execution alias. Always invoke via `.\.venv\Scripts\python.exe` or `py -3.12`.

### Step 2.3: Install Dependencies
```powershell
.\.venv\Scripts\pip.exe install -r requirements.txt
```

### Step 2.4: Verify Installation & Run Tests
```powershell
# Run the geometry tests
.\.venv\Scripts\python.exe -m unittest tests/test_geometry.py

# Run the core tracking tests
.\.venv\Scripts\python.exe -m unittest tests/test_core.py

# Run the entire test suite
.\.venv\Scripts\python.exe -m unittest discover tests
```

---

## 3. Setup on Linux & Raspberry Pi OS

### Step 3.1: Install System Packages
On Ubuntu, Debian, or Raspberry Pi OS (Debian-based):
```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python3-dev \
    libgl1 libglib2.0-0 v4l-utils libatlas-base-dev
```

### Step 3.2: Configure Camera & User Permissions (Raspberry Pi)
For USB webcams or CSI cameras:
```bash
# Add current user to video group
sudo usermod -aG video $USER

# Check available video devices
v4l2-ctl --list-devices
```

### Step 3.3: Create Virtual Environment and Install
```bash
cd intelligent_tracker

# Create venv
python3 -m venv .venv
source .venv/bin/activate

# Upgrade pip and install
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

### Step 3.4: Headless / Remote Server Mode
If running on a remote headless Raspberry Pi or server without an X11/Wayland display:
```bash
# Use offscreen Matplotlib backend
export MPLBACKEND=Agg
export QT_QPA_PLATFORM=offscreen

# Or replace opencv-contrib-python with headless variant:
pip install opencv-python-headless
```

---

## 4. Setup on macOS (Apple Silicon & Intel)

### Step 4.1: Install Prerequisites via Homebrew
```bash
brew install python@3.12
```

### Step 4.2: Create Virtual Environment
```bash
cd intelligent_tracker
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

### Step 4.3: Camera Permissions
When running camera captures on macOS:
- macOS requires explicit Camera permission for the terminal application (e.g., Terminal, iTerm2, or VS Code).
- Navigate to **System Settings > Privacy & Security > Camera** and ensure your terminal emulator is toggled on.

---

## 5. Edge AI Model Weights & Environment Diagnostics

### Step 5.1: Run Environment Diagnostics
Verify Python, OpenCV camera device indexing, active GUI backend, and ONNX Runtime execution providers:
```powershell
# Windows
.\.venv\Scripts\python.exe scripts/diagnostics.py

# Linux / macOS
source .venv/bin/activate
python scripts/diagnostics.py
```

### Step 5.2: Download Edge AI Models (ONNX)
Download verified, ultralightweight YOLOv8 Nano or YOLO11 Nano models with mirror failover and SHA-256 integrity verification:
```powershell
# Windows
.\.venv\Scripts\python.exe scripts/download_models.py --model yolov8n
.\.venv\Scripts\python.exe scripts/download_models.py --model yolo11n

# Linux / macOS
source .venv/bin/activate
python scripts/download_models.py --model yolov8n
python scripts/download_models.py --model yolo11n
```

---

## 6. Running the Application & Execution Recipes

### Pre-Run Verification & Diagnostics
```powershell
# 1. Verify model weights and SHA-256 integrity
.\.venv\Scripts\python.exe scripts/download_models.py --status

# 2. Check camera hardware indices and ONNX execution providers
.\.venv\Scripts\python.exe scripts/diagnostics.py

# 3. Run full automated test suite (all 63 tests)
$env:MPLBACKEND="Agg"
.\.venv\Scripts\python.exe -m unittest discover tests
```

### Sample Executions
```powershell
# Windows: Run YAML-configured synthetic demo with tripwires & zones
.\.venv\Scripts\python.exe main.py --config configs/demo.yaml

# Windows: Run YOLOv8 on default webcam with real-time heatmap overlay
.\.venv\Scripts\python.exe main.py --detector yolov8 --source 0 --heatmap

# Filter for specific classes (e.g., person only) with high confidence
.\.venv\Scripts\python.exe main.py --detector yolov8 --classes person --conf 0.40

# Headless benchmark with automated annotated video recording
.\.venv\Scripts\python.exe main.py --config configs/demo.yaml --headless --frames 60 --output demo_recording.mp4

# Run with pure NumPy SORT (Kalman filter) tracker
.\.venv\Scripts\python.exe main.py --config configs/demo.yaml --tracker sort --headless --frames 60

# Production RTSP retail surveillance template
.\.venv\Scripts\python.exe main.py --config configs/retail.yaml
```

### Scenario Combinations Matrix
| Scenario / Objective | Detector | Tracker | Source (`--source`) | Config File | Key Parameters | Mode | Full Runnable PowerShell Command |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Synthetic CI Smoke Test** | `mock` | `centroid` | `synthetic` | `configs/demo.yaml` | `--headless --frames 30` | Headless (30f) | `.\.venv\Scripts\python.exe main.py --config configs/demo.yaml --headless --frames 30` |
| **YOLOv8 Edge AI Benchmark** | `yolov8` | `centroid` | `synthetic` | `configs/demo.yaml` | `--detector yolov8 --headless --frames 60` | Headless (60f) | `.\.venv\Scripts\python.exe main.py --config configs/demo.yaml --detector yolov8 --headless --frames 60` |
| **YOLO11 Performance Test** | `yolo11` | `centroid` | `synthetic` | `configs/demo.yaml` | `--detector yolo11 --headless --frames 100` | Headless (100f) | `.\.venv\Scripts\python.exe main.py --config configs/demo.yaml --detector yolo11 --headless --frames 100` |
| **SORT Kalman Tracking Benchmark** | `mock` | `sort` | `synthetic` | `configs/demo.yaml` | `--tracker sort --headless --frames 60` | Headless (60f) | `.\.venv\Scripts\python.exe main.py --config configs/demo.yaml --tracker sort --headless --frames 60` |
| **Headless Video Export** | `yolov8` | `centroid` | `synthetic` | `configs/demo.yaml` | `--output recording.mp4 --headless --frames 90` | Headless Record | `.\.venv\Scripts\python.exe main.py --config configs/demo.yaml --detector yolov8 --output recording.mp4 --headless --frames 90` |
| **Retail Person Counting (Webcam)** | `yolov8` | `centroid` | `0` | - | `--classes person --conf 0.40` | Interactive GUI | `.\.venv\Scripts\python.exe main.py --detector yolov8 --source 0 --classes person --conf 0.40` |
| **Store Foot-Traffic & Heatmap** | `yolov8` | `centroid` | `0` | `configs/retail.yaml` | `--heatmap` | Interactive GUI | `.\.venv\Scripts\python.exe main.py --config configs/retail.yaml --source 0 --heatmap` |
| **RTSP IP Camera Surveillance** | `yolov8` | `centroid` | `rtsp://...` | `configs/retail.yaml` | - | Interactive / Stream | `.\.venv\Scripts\python.exe main.py --config configs/retail.yaml --source rtsp://192.168.1.100/stream1` |
| **Vehicle / Traffic Monitoring** | `yolov8` | `centroid` | `traffic.mp4` | - | `--classes car truck bus --conf 0.50` | Interactive GUI | `.\.venv\Scripts\python.exe main.py --detector yolov8 --source traffic.mp4 --classes car truck bus --conf 0.50` |
| **Legacy Face Tracking** | `face` | `centroid` | `0` | - | - | Interactive GUI | `.\.venv\Scripts\python.exe main.py --detector face --source 0` |
| **Color Blob / Marker Tracking** | `color` | `centroid` | `0` | - | - | Interactive GUI | `.\.venv\Scripts\python.exe main.py --detector color --source 0` |
| **Headless Remote Server / RPi** | `yolov8` | `centroid` | `synthetic` | `configs/demo.yaml` | `--headless --frames 120` | Headless Offscreen | `$env:MPLBACKEND="Agg"; .\.venv\Scripts\python.exe main.py --config configs/demo.yaml --detector yolov8 --headless --frames 120` |

### CLI Command Options
| Flag | Default | Description |
| :--- | :--- | :--- |
| `--config` | `None` | Path to YAML/JSON configuration file (e.g. `configs/demo.yaml`, `configs/retail.yaml`) |
| `--detector` | `haar` | Detection architecture (`yolov8`, `yolo11`, `haar`, `mock`, `face`, `eye`, `color`) |
| `--tracker` | `centroid` | Multi-object tracking algorithm (`centroid`, `sort`) |
| `--source` | `0` | Camera index (`0`, `1`), `synthetic`/`mock`, video file path, or RTSP URL |
| `--resolution`| `640x480` | Input resolution (`WIDTHxHEIGHT`) |
| `--framerate` | `30` | Target processing frame rate |
| `--conf` | `0.25` | Confidence threshold for AI detectors (`0.0` to `1.0`) |
| `--classes` | `None` | Filter detected classes (e.g. `person`, `car`, or class IDs like `0`) |
| `--heatmap` | `False` | Enable live 2D spatial occupancy heatmap overlay |
| `--output` | `None` | Output path to save annotated video recording (`output.mp4`) |
| `--headless` | `False` | Run without GUI window (ideal for CI/CD, remote SSH, and benchmarking) |
| `--frames` | `60` | Number of frames to process in headless mode (`0` = infinite) |

### Interactive GUI Controls:
- `q`: Quit active window and finalize telemetry.
- `d`: Clear / reset active tracks.
- `h`: Toggle live 2D spatial occupancy heatmap overlay.
- `s`: Save instantaneous snapshot image (`snapshot_<timestamp>.png`) and analytics report (`analytics_report_<timestamp>.json`).

---

## 7. Modernization Roadmap Status

The project evolves according to `TODO_MODERNIZATION.md` and `milestone_plan.md`:

1. ✅ **Milestone 1: Environment & Core Engine Revitalization**:
   - Python 3.12 modern virtual environment, cross-platform fixes, 21 unit tests passing.
2. ✅ **Milestone 2: Edge AI Detection Architecture**:
   - Modular `BaseDetector` interface and `DetectorFactory` registry.
   - Ultralight ONNX Runtime inference (`yolov8n.onnx`, `yolo11n.onnx`) with pure NumPy letterboxing and vectorized multi-class NMS.
   - Full backwards compatibility for Haar cascades and color detection.
   - 46/46 unit tests passing.
3. ✅ **Milestone 3: RTSP Stream Pipelines & Retail / Occupancy Analytics**:
   - Threaded non-blocking RTSP video reader with auto-reconnection and zero-latency frame drop.
   - Polygonal ROI zones, entry/exit tripwire line intersections, dwell times, and 2D spatial occupancy heatmaps.
   - Declarative YAML configs (`configs/demo.yaml`, `configs/retail.yaml`), video recording, and 63/63 tests passing.
4. ⬜ **Milestone 4: Object Identity Gallery, Re-Identification (Re-ID) & Sighting Database**:
   - Persistent SQLite entity database, visual Re-ID embeddings (ONNX + color descriptor fallback), interactive screen selection/tagging, cross-session re-appearance matching, and offline recording occurrence analytics.
5. ⬜ **Milestone 5: Modern Web Dashboard, Packaging & Edge Deployment**:
   - FastAPI / WebSocket live dashboard, Docker containerization (ARM64 / amd64), and systemd service configurations.


