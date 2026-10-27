#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Model download utility for Intelligent Tracker.
Downloads and verifies pre-exported ONNX models (YOLOv8n, YOLO11n) for Edge AI detection.
"""

import os
import sys
import hashlib
import argparse
import urllib.request as urllib_request
from urllib.error import URLError, HTTPError

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
DEFAULT_MODELS_DIR = os.path.join(REPO_ROOT, "models")

MODELS = {
    "yolov8n": {
        "filename": "yolov8n.onnx",
        "urls": [
            "https://huggingface.co/cabelo/yolov8/resolve/main/yolov8n.onnx",
            "https://huggingface.co/Kalray/yolov8/resolve/main/yolov8n.onnx",
            "https://huggingface.co/Xuban/yolo_weights_database/resolve/main/yolov8n.onnx",
        ],
        "sha256": "c03e8dc50385b49f150a8de1b3fa6f3f8a0ba0ce2a458a353179c084f8012f35",
        "size_bytes": 12823589,
        "description": "YOLOv8 Nano object detection model (COCO 80 classes, ~12.8 MB)",
    },
    "yolo11n": {
        "filename": "yolo11n.onnx",
        "urls": [
            "https://huggingface.co/unileon-robotics/YOLO11-ONNX/resolve/main/yolo11n.onnx",
        ],
        "sha256": "baeb4c1d6f3bb460689823cc2d40daa31e6156f2517fcd48aab0db9490d9f4e5",
        "size_bytes": 10699288,
        "description": "YOLO11 Nano object detection model (COCO 80 classes, ~10.7 MB)",
    },
    "osnet_x0_25": {
        "filename": "osnet_x0_25.onnx",
        "urls": [
            "https://huggingface.co/kornia/osnet/resolve/main/osnet_x0_25_msmt17.onnx",
            "https://huggingface.co/anriha/osnet_x0_25_msmt17/resolve/main/osnet_x0_25_msmt17.onnx",
        ],
        "sha256": "e78604f4ccda49b8f41cd0f8f7303800ce75d2361895ebb0729513c1bf53d277",
        "size_bytes": 907169,
        "description": "OSNet x0.25 lightweight visual Re-ID embedding model (~907 KB)",
    },
    "yunet": {
        "filename": "face_detection_yunet_2023mar.onnx",
        "urls": [
            "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        ],
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "size_bytes": 232589,
        "description": "YuNet ONNX high-speed lightweight face detector model (~232 KB)",
    },
}

try:
    import ssl
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CONTEXT = None


def compute_sha256(filepath):
    """Compute SHA-256 hash of a file in streaming chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def download_file(urls, destination, expected_sha256=None, expected_size=None):
    """
    Download a file from a list of candidate URLs with atomic write and SHA-256 verification.
    """
    dest_dir = os.path.dirname(destination)
    if dest_dir and not os.path.exists(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)

    temp_path = destination + ".tmp"
    last_error = None

    for url in urls:
        print("[INFO] Attempting download from: {}".format(url))
        try:
            req = urllib_request.Request(url, headers={"User-Agent": "Mozilla/5.0 (IntelligentTracker/2.0)"})
            open_kwargs = {"timeout": 60}
            if _SSL_CONTEXT is not None:
                open_kwargs["context"] = _SSL_CONTEXT
            with urllib_request.urlopen(req, **open_kwargs) as response:
                total_size = response.headers.get("Content-Length")
                total_size = int(total_size) if total_size and total_size.isdigit() else expected_size
                downloaded = 0
                hasher = hashlib.sha256()

                with open(temp_path, "wb") as out_f:
                    while True:
                        buffer = response.read(65536)
                        if not buffer:
                            break
                        downloaded += len(buffer)
                        out_f.write(buffer)
                        hasher.update(buffer)

                        if total_size:
                            percent = (downloaded / total_size) * 100
                            mb_down = downloaded / (1024 * 1024)
                            mb_tot = total_size / (1024 * 1024)
                            sys.stdout.write("\r[DOWNLOADING] {:.2f}MB / {:.2f}MB ({:.1f}%)".format(mb_down, mb_tot, percent))
                        else:
                            mb_down = downloaded / (1024 * 1024)
                            sys.stdout.write("\r[DOWNLOADING] {:.2f}MB".format(mb_down))
                        sys.stdout.flush()

                print("")
                actual_sha256 = hasher.hexdigest()

                if expected_sha256 and actual_sha256 != expected_sha256:
                    print("[WARNING] Checksum mismatch from {}. Expected: {}, got: {}".format(url, expected_sha256, actual_sha256))
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    continue

                # Move temp file to final destination
                if os.path.exists(destination):
                    os.remove(destination)
                os.rename(temp_path, destination)
                print("[SUCCESS] Verified SHA-256: {}".format(actual_sha256))
                return True

        except Exception as e:
            last_error = e
            print("[WARNING] Failed downloading from {}: {}".format(url, e))
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    raise RuntimeError("Failed to download file from all candidate URLs. Last error: {}".format(last_error))


def download_model(model_name, output_dir=None, force=False):
    """
    Download a registered model by name.

    :param model_name: 'yolov8n', 'yolo11n', or 'all'
    :param output_dir: directory to store model files (default: repo/models)
    :param force: re-download even if already present and verified
    :return: path to model file (or dict of paths if 'all')
    """
    if output_dir is None:
        output_dir = DEFAULT_MODELS_DIR

    model_key = model_name.lower().strip()
    if model_key == "all":
        results = {}
        for k in sorted(MODELS.keys()):
            results[k] = download_model(k, output_dir=output_dir, force=force)
        return results

    if model_key not in MODELS:
        raise ValueError("Unknown model '{}'. Available: {}".format(model_name, list(MODELS.keys()) + ["all"]))

    info = MODELS[model_key]
    dest_path = os.path.join(output_dir, info["filename"])

    if os.path.isfile(dest_path) and not force:
        print("[CHECK] Verifying existing model file: {}".format(dest_path))
        existing_sha = compute_sha256(dest_path)
        if existing_sha == info["sha256"]:
            print("[INFO] Model '{}' already exists and matches SHA-256 ({}).".format(model_key, existing_sha))
            return dest_path
        else:
            print("[WARNING] Existing file checksum differs. Re-downloading...")

    print("[INFO] Downloading model '{}': {}".format(model_key, info["description"]))
    download_file(
        urls=info["urls"],
        destination=dest_path,
        expected_sha256=info["sha256"],
        expected_size=info.get("size_bytes"),
    )
    return dest_path


def ensure_model(model_name, output_dir=None):
    """
    Ensure the requested model is downloaded and ready for use.
    If the file exists and is valid, returns immediately.
    """
    return download_model(model_name, output_dir=output_dir, force=False)


def check_status(output_dir=None):
    """Check and display presence and integrity of all known models."""
    if output_dir is None:
        output_dir = DEFAULT_MODELS_DIR
    print("=" * 60)
    print("AI Model Weights Status ({})".format(output_dir))
    print("=" * 60)
    for model_key, meta in MODELS.items():
        dest = os.path.join(output_dir, meta["filename"])
        if not os.path.isfile(dest):
            print("  [-] {:<12}: MISSING ({})".format(model_key, meta["filename"]))
        else:
            size_mb = os.path.getsize(dest) / (1024.0 * 1024.0)
            file_hash = compute_sha256(dest)
            if file_hash.lower() == meta["sha256"].lower():
                print("  [+] {:<12}: VALID ({:.2f} MB, SHA-256 OK)".format(model_key, size_mb))
            else:
                print("  [!] {:<12}: CORRUPT (Hash mismatch: expected {}, got {})".format(
                    model_key, meta["sha256"][:12], file_hash[:12]))
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Download ONNX models for Intelligent Tracker.")
    parser.add_argument(
        "--model",
        default="yolov8n",
        choices=list(MODELS.keys()) + ["all"],
        help="Model to download (default: yolov8n)",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_MODELS_DIR,
        help="Directory to save downloaded models (default: ./models)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if model file already exists and is valid",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check presence and SHA-256 integrity of all known models without downloading",
    )
    args = parser.parse_args()

    if args.status:
        check_status(output_dir=args.output_dir)
        return

    try:
        path = download_model(args.model, output_dir=args.output_dir, force=args.force)
        print("[COMPLETED] Model path(s):", path)
    except Exception as e:
        print("[ERROR]", e)
        sys.exit(1)


if __name__ == "__main__":
    main()

