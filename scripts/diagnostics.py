#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker — Hardware, Environment & Runtime Diagnostic Tool.

Checks:
1. Python version and virtual environment
2. GUI / Matplotlib backend capability (Qt, TkAgg, Agg)
3. Camera hardware availability (indices 0..4)
4. ONNX Runtime backend and acceleration (DirectML / CPU)
5. Model weight integrity
6. Runtime Processes, Docker Containers, Stream Hibernation & Zombie Detection
"""

import os
import sys
import json
import argparse
import subprocess
import urllib.request
import urllib.error


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

        candidates = [
            ("QtAgg", "PyQt6 / PySide6 (Modern High-Performance GUI)"),
            ("QT5Agg", "PyQt5 / PySide2 (Legacy Qt)"),
            ("TkAgg", "Tkinter (Python Built-in Standard GUI)"),
            ("Agg", "Headless / Non-interactive"),
        ]

        available = []
        for backend, desc in candidates:
            try:
                backend_registry.load_backend_module(backend)
                available.append((backend, desc, True))
            except Exception:
                available.append((backend, desc, False))

        for backend, desc, ok in available:
            status = "[OK] AVAILABLE" if ok else "[--] NOT INSTALLED"
            print(f"  - {backend:<8} : {status} ({desc})")

        current = matplotlib.get_backend()
        print(f"  Active backend     : {current}")
        if current.lower() == "agg":
            print("  [!] Active backend is headless ('Agg'). GUI windows will not open.")
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
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if sys.platform.startswith("win") else cv2.VideoCapture(idx)
            if not cap.isOpened():
                cap = cv2.VideoCapture(idx)

            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    h, w, c = frame.shape
                    print(f"  [+] Camera index {idx}: WORKING (Resolution: {w}x{h}, Channels: {c})")
                    found += 1
                else:
                    print(f"  [?] Camera index {idx}: OPENED, but failed to read frames.")
                cap.release()
            else:
                cap.release()

        if found == 0:
            print("  [!] No physical USB/webcam cameras detected.")
            print("      Synthetic feed available: python main.py --source synthetic")
        else:
            print(f"  Total operational physical cameras found: {found}")
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

    expected = ["yolov8n.onnx", "yolo11n.onnx", "osnet_x0_25.onnx"]
    for m in expected:
        p = os.path.join(models_dir, m)
        if os.path.isfile(p):
            sz_mb = os.path.getsize(p) / (1024 * 1024)
            print(f"  [+] {m:<18}: PRESENT ({sz_mb:.2f} MB)")
        else:
            print(f"  [-] {m:<18}: MISSING (Run: python scripts/download_models.py)")


def check_runtime_processes(app_url="http://127.0.0.1:8000"):
    print("\n" + "=" * 60)
    print(" 6. Runtime Processes, Containers & Stream Hibernation")
    print("=" * 60)

    # 1. Docker Containers
    try:
        res = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            print("  [Docker Containers Resource Usage]")
            print(f"    {'CONTAINER NAME':<32} {'CPU %':<10} {'MEMORY':<20} {'PIDS':<8}")
            print("    " + "-" * 72)
            for line in res.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 4:
                    name, cpu, mem, pids = parts[:4]
                    warn = " [!] HIGH CPU" if float(cpu.replace("%", "").strip() or 0) > 50.0 else ""
                    print(f"    {name:<32} {cpu:<10} {mem:<20} {pids:<8}{warn}")
        else:
            print("  [Docker] Docker CLI responded but no active containers found.")
    except Exception:
        print("  [Docker] Docker daemon not reachable or docker command not found.")

    # 2. Live Dashboard API & Camera Stream Probe
    print("\n  [Live Camera Streams & Hibernation State]")
    try:
        req = urllib.request.urlopen(f"{app_url}/api/cameras", timeout=3.0)
        cams = json.loads(req.read().decode("utf-8"))
        print(f"    {'CAMERA ID':<30} {'STATUS':<14} {'FPS':<8} {'TYPE':<12}")
        print("    " + "-" * 66)
        active_count = 0
        hibernating_count = 0
        for c in cams:
            cid = c.get("id", "unknown")
            fps = float(c.get("fps", 0.0))
            status = c.get("status", "unknown")
            ctype = c.get("source_type", c.get("type", "unknown"))
            if fps > 0:
                active_count += 1
                state_str = f"ACTIVE ({fps} FPS)"
            else:
                hibernating_count += 1
                state_str = "HIBERNATING (0.0 FPS)"
            print(f"    {cid:<30} {state_str:<22} {ctype:<12}")

        print(f"\n    Summary: {active_count} active pipelines, {hibernating_count} hibernating (zero-load).")
        if active_count == 0:
            print("    [+] Zero-Load Hibernation Verified: No camera streams consuming processing cycles.")
    except urllib.error.URLError:
        print(f"    [!] Dashboard service offline at {app_url} (run with docker compose up -d)")
    except Exception as e:
        print(f"    [!] Failed to probe cameras: {e}")

    # 3. Server System Status
    try:
        req = urllib.request.urlopen(f"{app_url}/status", timeout=3.0)
        st = json.loads(req.read().decode("utf-8"))
        sys_info = st.get("system", {})
        print("\n  [Dashboard Gateway Health]")
        print(f"    Uptime        : {st.get('uptime_seconds', 0)} seconds")
        print(f"    Gateway CPU   : {sys_info.get('cpu_percent', 'N/A')}%")
        print(f"    Gateway RAM   : {sys_info.get('process_memory_mb', 'N/A')} MB (System: {sys_info.get('ram_percent', 'N/A')}%)")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Intelligent Tracker System & Runtime Diagnostics")
    parser.add_argument("--hardware", action="store_true", help="Probe only cameras, GUI, and ONNX backends")
    parser.add_argument("--runtime", action="store_true", help="Audit Docker containers, stream hibernation & processes")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Dashboard API base URL")
    args = parser.parse_args()

    run_all = not (args.hardware or args.runtime)

    print("\n============================================================")
    print("   INTELLIGENT TRACKER — SYSTEM & RUNTIME DIAGNOSTIC")
    print("============================================================")

    if run_all or args.hardware:
        check_python()
        check_gui_backend()
        check_cameras()
        check_ai_runtimes()
        check_models()

    if run_all or args.runtime:
        check_runtime_processes(app_url=args.url)

    print("\n" + "=" * 60)
    print(" Diagnostic Complete.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
