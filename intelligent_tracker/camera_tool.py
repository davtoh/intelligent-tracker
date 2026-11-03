#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Hardware Camera Diagnostic & Resource Manager Tool.

Provides:
- Camera device listing with friendly hardware names and busy/free status inspection.
- Targeted camera releasing by index (--release-camera <INDEX>).
- Targeted process termination by PID (--kill-pid <PID> [--force]).
- Diagnostic probing for frame decode health and true measured FPS.
- Recovery routines to safely release locked DirectShow COM filter graphs on Windows.
- Identification and cleanup of orphaned background worker processes holding video handles.
"""

import os
import sys
import time
import argparse
import logging
from typing import Dict, List, Optional, Any

import cv2
import psutil

from intelligent_tracker.camera_device import CameraDeviceHandler

logger = logging.getLogger("intelligent_tracker.camera_tool")


def inspect_camera_devices(max_devices: int = 6) -> List[Dict[str, Any]]:
    """
    Inspect all camera devices and return their current operational status.

    Status categories:
    - 'AVAILABLE': Device present and ready for frame acquisition.
    - 'BUSY (LOCKED)': Device present on OS, but currently locked by another application/process.
    - 'NOT PRESENT': No device connected at this hardware index.
    """
    known_names = CameraDeviceHandler.get_device_names()
    results = []

    for idx in range(max_devices):
        friendly_name = known_names[idx] if idx < len(known_names) else f"USB Camera {idx}"
        is_virt = CameraDeviceHandler.is_virtual_device(friendly_name)

        # Probe device
        cap, backend = CameraDeviceHandler.open_camera(idx, test_read=True)
        if cap and cap.isOpened():
            ret, frame = cap.read()
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
            CameraDeviceHandler.safe_release(cap, settle_delay=0.15)
            status = "AVAILABLE" if (ret and CameraDeviceHandler.validate_frame(frame)) else "NO_FRAME"
            res_str = f"{w}x{h}"
        else:
            CameraDeviceHandler.safe_release(cap, settle_delay=0.05)
            # If name exists in OS registry, check virtual vs physical lock
            if idx < len(known_names):
                status = "IDLE (OFFLINE)" if is_virt else "BUSY (LOCKED)"
                res_str = "-"
                fps = 0.0
            else:
                status = "NOT PRESENT"
                res_str = "-"
                fps = 0.0

        results.append({
            "index": idx,
            "name": friendly_name,
            "status": status,
            "resolution": res_str,
            "fps": round(fps, 1) if fps > 0 else "-",
            "is_virtual": is_virt,
        })

    return results


def find_camera_worker_processes(include_self: bool = False) -> List[Dict[str, Any]]:
    """
    Identify running Python processes on the system that might be holding video capture handles.
    Excludes the active camera_tool / camera_manager execution context.
    """
    current_pid = os.getpid()
    parent_pid = os.getppid() if hasattr(os, "getppid") else None
    camera_procs = []

    for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time", "memory_info"]):
        try:
            pinfo = proc.info
            name = (pinfo.get("name") or "").lower()
            if "python" in name:
                pid = pinfo["pid"]
                if not include_self and (pid == current_pid or pid == parent_pid):
                    continue
                cmdline = " ".join(pinfo.get("cmdline") or [])
                # Ignore self when script name is in cmdline
                if not include_self and ("camera_manager" in cmdline or "camera_tool" in cmdline):
                    continue
                mem_mb = round(pinfo["memory_info"].rss / (1024 * 1024), 1) if pinfo.get("memory_info") else 0.0
                camera_procs.append({
                    "pid": pid,
                    "name": name,
                    "cmdline": cmdline,
                    "memory_mb": mem_mb,
                    "is_tracker": ("main.py" in cmdline or "uvicorn" in cmdline or "dashboard" in cmdline),
                    "is_self": (pid == current_pid),
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return camera_procs


def terminate_process_by_pid(pid: int, force: bool = False) -> bool:
    """
    Safely terminate a specific process by PID, optionally forcing with SIGKILL.
    """
    try:
        p = psutil.Process(pid)
        if force:
            p.kill()
        else:
            p.terminate()
            try:
                p.wait(timeout=2.0)
            except psutil.TimeoutExpired:
                p.kill()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        logger.warning("Could not terminate PID %d: %s", pid, e)
        return False


def release_camera_by_index(index: int, force: bool = False) -> Dict[str, Any]:
    """
    Target a specific camera index to release its hardware locks:
    1. Identifies any python worker running this index (e.g. main.py --source <idx>).
    2. Cycles VideoCapture open and release with COM driver cooldown.
    3. Re-probes the camera to confirm availability.
    """
    procs = find_camera_worker_processes()
    killed = []
    for p in procs:
        cmdline = p.get("cmdline", "")
        if f"--source {index}" in cmdline or f"-s {index}" in cmdline or f"source={index}" in cmdline:
            if terminate_process_by_pid(p["pid"], force=force):
                killed.append(p["pid"])

    CameraDeviceHandler.safe_release(None, settle_delay=0.4)
    dev_info = CameraDeviceHandler.probe_device(index)
    is_available = dev_info is not None and dev_info.get("valid", False)

    return {
        "index": index,
        "available": is_available,
        "terminated_pids": killed,
        "device_info": dev_info,
    }


def release_camera_resources(kill_orphans: bool = False, force: bool = False) -> Dict[str, Any]:
    """
    Execute hardware unbind cooldown and optionally terminate lingering background tracker processes.
    """
    CameraDeviceHandler.safe_release(None, settle_delay=0.4)
    killed = []

    if kill_orphans:
        procs = find_camera_worker_processes()
        for p in procs:
            if p["is_tracker"]:
                if terminate_process_by_pid(p["pid"], force=force):
                    killed.append(p["pid"])

        if killed:
            time.sleep(0.5)
            CameraDeviceHandler.safe_release(None, settle_delay=0.3)

    return {
        "success": True,
        "cooldown_applied_seconds": 0.4,
        "processes_terminated": killed,
    }


def print_camera_status_table(devices: List[Dict[str, Any]], processes: List[Dict[str, Any]]) -> None:
    """Pretty print ASCII inspection table for terminal users."""
    print("=" * 76)
    print("Intelligent Tracker - Hardware Video Capture & Device Status")
    print("=" * 76)
    print(f"{'Idx':<4} {'Friendly Name':<28} {'Resolution':<12} {'FPS':<6} {'Type':<9} {'Status'}")
    print("-" * 76)

    for dev in devices:
        if dev["status"] == "NOT PRESENT" and dev["index"] >= 3:
            continue
        dev_type = "Virtual" if dev["is_virtual"] else "Hardware"
        print(f"#{dev['index']:<3} {dev['name']:<28} {str(dev['resolution']):<12} {str(dev['fps']):<6} {dev_type:<9} {dev['status']}")

    print("=" * 76)

    if processes:
        print("\nActive Python Video/Tracker Processes on Host:")
        for p in processes:
            tag = "[TRACKER/DASHBOARD]" if p["is_tracker"] else "[PYTHON]"
            print(f"  - PID {p['pid']:<6} | {tag:<19} | {p['memory_mb']:>6.1f} MB | {p['cmdline'][:60]}")
        print("\nManagement Options:")
        print("  - Release a specific camera : python scripts/camera_manager.py --release-camera <INDEX>")
        print("  - Terminate a specific PID  : python scripts/camera_manager.py --kill-pid <PID> [--force]")
        print("  - Terminate all workers     : python scripts/camera_manager.py --release --kill-orphans\n")
    else:
        print("\nNo other Python video processes running on host.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Intelligent Tracker - Hardware Camera Status & Resource Manager",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--status", "--list", action="store_true", help="List connected cameras and their availability status")
    parser.add_argument("--release", action="store_true", help="Release DirectShow driver graphs and apply settle cooldown")
    parser.add_argument("--release-camera", "--free", type=int, default=None, metavar="INDEX", help="Force release a specific camera index")
    parser.add_argument("--kill-pid", type=int, nargs="+", default=None, metavar="PID", help="Terminate one or more specific processes by PID")
    parser.add_argument("--kill-orphans", action="store_true", help="Terminate orphaned background python tracker workers")
    parser.add_argument("--force", "-f", action="store_true", help="Force kill processes (SIGKILL) rather than graceful SIGTERM")
    parser.add_argument("--test", type=int, default=None, help="Test acquisition from a specific camera index")

    args = parser.parse_args()

    # 1. Kill specific PIDs if requested
    if args.kill_pid:
        for pid in args.kill_pid:
            success = terminate_process_by_pid(pid, force=args.force)
            if success:
                print(f"[SUCCESS] Terminated process PID {pid} (force={args.force}).")
            else:
                print(f"[ERROR] Failed to terminate PID {pid}.")
        CameraDeviceHandler.safe_release(None, settle_delay=0.3)

    # 2. Release specific camera index if requested
    if args.release_camera is not None:
        idx = args.release_camera
        res = release_camera_by_index(idx, force=args.force)
        avail_str = "AVAILABLE" if res["available"] else "BUSY / INACCESSIBLE"
        print(f"[INFO] Camera #{idx} release sequence complete. Status: {avail_str}")
        if res["terminated_pids"]:
            print(f"[INFO] Terminated workers: {res['terminated_pids']}")

    # 3. Global release / orphan kill
    if args.release or args.kill_orphans:
        res = release_camera_resources(kill_orphans=args.kill_orphans, force=args.force)
        print(f"[INFO] Camera resources released (cooldown {res['cooldown_applied_seconds']}s).")
        if res["processes_terminated"]:
            print(f"[INFO] Terminated orphaned worker PIDs: {res['processes_terminated']}")

    # 4. Test specific index
    if args.test is not None:
        idx = args.test
        name = CameraDeviceHandler.get_friendly_name(idx)
        print(f"[INFO] Testing acquisition from device #{idx} ('{name}')...")
        cap, backend = CameraDeviceHandler.open_camera(idx, test_read=True)
        if not cap or not cap.isOpened():
            print(f"[ERROR] Failed to open device #{idx}. Device may be in use or not present.")
            sys.exit(1)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        print(f"[SUCCESS] Connected via {backend}: {w}x{h} @ {fps} FPS")
        CameraDeviceHandler.safe_release(cap, settle_delay=0.25)
        return

    # If only kill-pid or release-camera was passed without --status, we can finish or show status
    if args.kill_pid or args.release_camera is not None:
        return

    # Default action: status list
    devs = inspect_camera_devices(max_devices=5)
    procs = find_camera_worker_processes()
    print_camera_status_table(devs, procs)


if __name__ == "__main__":
    main()
