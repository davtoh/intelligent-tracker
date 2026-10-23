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

## 6. Running the Application

### Running with Edge AI Detectors
```powershell
# Windows: Run YOLOv8 Nano on default webcam
.\.venv\Scripts\python.exe main.py --detector yolov8 --source 0

# Windows: Run YOLO11 Nano on synthetic feed (no camera required)
.\.venv\Scripts\python.exe main.py --detector yolo11 --source synthetic

# Filter for specific classes (e.g., person only)
.\.venv\Scripts\python.exe main.py --detector yolov8 --classes person --conf 0.4

# Run headless benchmark (ideal for CI, servers, Raspberry Pi testing)
.\.venv\Scripts\python.exe main.py --detector yolov8 --source synthetic --headless --frames 60

# Run with legacy Haar cascade or synthetic mock detector
.\.venv\Scripts\python.exe main.py --detector haar --source 0
.\.venv\Scripts\python.exe main.py --detector mock --source synthetic
```

### CLI Command Options
| Flag | Default | Description |
| :--- | :--- | :--- |
| `--detector` | `haar` | Detection architecture (`yolov8`, `yolo11`, `haar`, `mock`, `face`, `eye`, `color`) |
| `--source` | `0` | Camera index (`0`, `1`), `synthetic`/`mock`, video file path, or RTSP URL |
| `--resolution`| `640x480` | Input resolution (`WIDTHxHEIGHT`) |
| `--framerate` | `30` | Target processing frame rate |
| `--conf` | `0.25` | Confidence threshold for AI detectors (`0.0` to `1.0`) |
| `--classes` | `None` | Filter detected classes (e.g. `person`, `car`, or class IDs like `0`) |
| `--headless` | `False` | Run without GUI window (ideal for CI/CD, remote SSH, and benchmarking) |
| `--frames` | `60` | Number of frames to process in headless mode (`0` = infinite) |

### Controls in GUI Window:
- `q`: Quit active window / application.
- `d`: Clear tracked objects in the current scene.

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
3. ⬜ **Milestone 3: RTSP Stream Pipelines & Retail / Occupancy Analytics**:
   - Threaded non-blocking RTSP video reader with auto-reconnection and zero-latency frame drop.
   - Polygonal ROI zones, entry/exit tripwire line intersections, dwell times, and 2D spatial occupancy heatmaps.
4. ⬜ **Milestone 4: Edge Alerting & Event Dispatch**:
   - Webhooks (JSON POST), Telegram notifications (with snapshot frames), and MQTT telemetry for Smart Home / IoT platforms.
5. ⬜ **Milestone 5: Modern Web Dashboard, Packaging & Edge Deployment**:
   - FastAPI / WebSocket live dashboard, Docker containerization (ARM64 / amd64), and systemd service configurations.

