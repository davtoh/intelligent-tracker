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

## 5. Running the Application

### Running the Tracking Demo
```bash
# Windows
.\.venv\Scripts\python.exe main.py

# Linux / macOS
source .venv/bin/activate
python main.py
```

### Controls in GUI:
- `q`: Quit active window / application.

---

## 6. Modernization Architecture (Next Steps)

After establishing stable cross-platform execution, the project evolves according to `TODO_MODERNIZATION.md`:

1. **Detection Engine (YOLOv8 / YOLOv11 Edge)**:
   - Replacing legacy Haar cascade (`cv2.CascadeClassifier`) with ultra-light ONNX models (`yolov8n.onnx`, `yolov11n.onnx`).
   - Hardware acceleration options:
     - **Windows**: DirectML (`onnxruntime-directml`)
     - **Linux / Raspberry Pi**: CPU / OpenVINO / Coral Edge TPU (`onnxruntime`)
     - **macOS**: CoreML (`onnxruntime-silicon`)
2. **RTSP Stream Pipelines**:
   - Ingesting IP camera streams (`rtsp://username:password@camera_ip:554/stream1`) with automatic reconnection and frame-drop policies.
3. **Retail & Space Analytics**:
   - Polygonal ROI zones, entry/exit tripwire line intersections, dwell times, and 2D spatial occupancy heatmaps.
4. **Alerts & Integrations**:
   - Webhooks (JSON POST), Telegram notifications (with snapshot frames), and MQTT telemetry for Smart Home / IoT platforms.
