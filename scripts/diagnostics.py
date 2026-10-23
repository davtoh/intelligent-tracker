#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker — Hardware & Environment Diagnostic Tool.

Checks:
1. Python version and virtual environment
2. OpenCV build and camera availability (indices 0..4)
3. ONNX Runtime backend and acceleration (DirectML / CPU)
4. GUI / Matplotlib backend capability (Qt, TkAgg, Agg)
5. Model weight status
"""

import sys
import os

def check_python():
    print("=" * 60)
    print(" 1. Python Environment")
    print("=" * 60)
    print(f"  Python executable: {sys.executable}")
    print(f"  Python version   : {sys.version.split()[0]}")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    print(f"  In VirtualEnv    : {in_venv} ({sys.prefix})")


def check_gui_backend():
    print("\n" + "=" * 60)
    print(" 2. GUI / Visualization Backend")
    print("=" * 60)
    try:
        import matplotlib
        from matplotlib.backends.registry import backend_registry
        print(f"  Matplotlib version : {matplotlib.__version__}")
        
        candidates = [("QtAgg", "PyQt6 / PySide6 (Modern High-Performance GUI)"),
                      ("QT5Agg", "PyQt5 / PySide2 (Legacy Qt)"),
                      ("TkAgg", "Tkinter (Python Built-in Standard GUI)"),
                      ("Agg", "Headless / Non-interactive")]
        
        available = []
        for backend, desc in candidates:
            try:
                backend_registry.load_backend_module(backend)
                available.append((backend, desc, True))
            except Exception as e:
                available.append((backend, desc, False))
        
        for backend, desc, ok in available:
            status = "[OK] AVAILABLE" if ok else "[--] NOT INSTALLED"
            print(f"  - {backend:<8} : {status} ({desc})")

        current = matplotlib.get_backend()
        print(f"  Active backend     : {current}")
        if current.lower() == "agg":
            print("  [!] WARNING: Active backend is headless ('Agg'). GUI windows will not open.")
            print("      To enable GUI, install PyQt: pip install PyQt6")
    except Exception as e:
        print(f"  [ERROR] Matplotlib check failed: {e}")


def check_cameras(max_indices=4):
    print("\n" + "=" * 60)
    print(" 3. Camera Hardware Probing")
    print("=" * 60)
    try:
        import cv2
        print(f"  OpenCV Version: {cv2.__version__}")
        
        found = 0
        for idx in range(max_indices):
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(idx)
            
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    h, w, c = frame.shape
                    print(f"  [+] Camera index {idx}: WORKING (Resolution: {w}x{h}, Channels: {c})")
                    found += 1
                else:
                    print(f"  [?] Camera index {idx}: OPENED, but failed to read frames (may be busy in another app).")
                cap.release()
            else:
                cap.release()
                
        if found == 0:
            print("  [!] No hardware cameras detected.")
            print("      You can run with synthetic test feed using: python main.py --source mock")
        else:
            print(f"  Total operational cameras found: {found}")
    except Exception as e:
        print(f"  [ERROR] OpenCV camera probe failed: {e}")


def check_ai_runtimes():
    print("\n" + "=" * 60)
    print(" 4. AI & Acceleration Runtimes")
    print("=" * 60)
    try:
        import onnxruntime as ort
        print(f"  ONNX Runtime Version : {ort.__version__}")
        providers = ort.get_available_providers()
        print(f"  Execution Providers  : {', '.join(providers)}")
    except ImportError:
        print("  [!] ONNX Runtime not installed.")


def check_models():
    print("\n" + "=" * 60)
    print(" 5. AI Models Integrity")
    print("=" * 60)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models_dir = os.path.join(base_dir, "models")
    if not os.path.isdir(models_dir):
        print(f"  [!] Models directory not found at: {models_dir}")
        print("      Run: python scripts/download_models.py")
        return

    expected = ["yolov8n.onnx", "yolo11n.onnx"]
    for m in expected:
        p = os.path.join(models_dir, m)
        if os.path.isfile(p):
            sz_mb = os.path.getsize(p) / (1024 * 1024)
            print(f"  [+] {m:<15}: PRESENT ({sz_mb:.2f} MB)")
        else:
            print(f"  [-] {m:<15}: MISSING (Run: python scripts/download_models.py)")


def main():
    print("\n============================================================")
    print("   INTELLIGENT TRACKER — SYSTEM & HARDWARE DIAGNOSTIC")
    print("============================================================")
    check_python()
    check_gui_backend()
    check_cameras()
    check_ai_runtimes()
    check_models()
    print("\n" + "=" * 60)
    print(" Diagnostic Complete.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
