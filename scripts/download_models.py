#!/usr/bin/env python
"""Thin CLI wrapper for ONNX model download and verification."""

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from intelligent_tracker.detectors.model_loader import (
    DEFAULT_MODELS_DIR,
    MODELS,
    check_status,
    compute_sha256,
    download_file,
    download_model,
    ensure_model,
)

__all__ = [
    "DEFAULT_MODELS_DIR",
    "MODELS",
    "check_status",
    "compute_sha256",
    "download_file",
    "download_model",
    "ensure_model",
    "main",
]


def main() -> None:
    """Parse CLI arguments and run model status or download."""
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
    except Exception as exc:
        print("[ERROR]", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
