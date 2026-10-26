# Rule: Environment Discovery & Execution Standards

## Purpose
Prevent redundant searching, failed commands, and tool timeouts when running test suites or scripts across sessions. All AI assistants must immediately reference this document before executing project commands.

## Python Environments
- **Primary Virtualenv Path (Modern Python 3.12):** `.\.venv\` (relative to project root `g:\Mi unidad\projects\products\intelligent_tracker\.venv\`).
- **Python Executable (Windows / PowerShell):**
  ```powershell
  .\.venv\Scripts\python.exe
  ```
- **Pip Executable (Windows / PowerShell):**
  ```powershell
  .\.venv\Scripts\pip.exe
  ```
- **Fallback Legacy Conda Environment (Python 3.7):**
  `C:\ProgramData\Anaconda3\envs\InteligentTracker\python.exe` (historical reference with OpenCV 4.1.0 / PyQt5 5.13).
- **System `python` Warning:** The default Windows system path has Microsoft Store alias / Python 3.14 which lacks packages. **Never use unqualified `python` or `pip`**. Always use `.\.venv\Scripts\python.exe` or `py -3.12`.

## Execution Commands (Windows PowerShell)
- **Running the Full Test Suite:**
  ```powershell
  .\.venv\Scripts\python.exe -m unittest discover tests
  ```
- **Running Specific Unit Tests:**
  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests/test_geometry.py
  .\.venv\Scripts\python.exe -m unittest tests/test_core.py
  ```
- **Running the Main Tracker Application:**
  ```powershell
  .\.venv\Scripts\python.exe main.py
  ```
- **Installing / Updating Dependencies:**
  ```powershell
  .\.venv\Scripts\pip.exe install -r requirements.txt
  ```

## Cross-Platform Execution Reference

### Linux (Ubuntu / Debian / Raspberry Pi OS)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m unittest discover tests
python main.py
```

### macOS (Apple Silicon / Intel)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m unittest discover tests
python main.py
```

## Hardware & Headless Notes
- In headless CI/CD, remote SSH sessions, or systems without a physical monitor/X11/Wayland, use headless OpenCV (`opencv-python-headless`) or set `QT_QPA_PLATFORM=offscreen` / `MPLBACKEND=Agg` before running tests.
- When no physical webcam is connected, camera indices (e.g. `0`) will fail; the engine supports video file paths or synthetic frames.
