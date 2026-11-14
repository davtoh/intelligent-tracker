"""ONNX model registry, downloader, and SHA-256 integrity verifier."""

import hashlib
import os
import sys
import urllib.request as urllib_request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_DIR = str(REPO_ROOT / "models")

MODELS: dict[str, dict[str, object]] = {
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


def compute_sha256(filepath: str) -> str:
    """Compute SHA-256 hash of a file in streaming chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def download_file(
    urls: list[str],
    destination: str,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
) -> bool:
    """Download a file from candidate URLs with atomic write and SHA-256 verification."""
    dest_dir = os.path.dirname(destination)
    if dest_dir and not os.path.exists(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)

    temp_path = destination + ".tmp"
    last_error: Exception | None = None

    for url in urls:
        print(f"[INFO] Attempting download from: {url}")
        try:
            req = urllib_request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (IntelligentTracker/2.0)"}
            )
            open_kwargs: dict[str, object] = {"timeout": 60}
            if _SSL_CONTEXT is not None:
                open_kwargs["context"] = _SSL_CONTEXT
            with urllib_request.urlopen(req, **open_kwargs) as response:
                total_header = response.headers.get("Content-Length")
                total_size = int(total_header) if total_header and total_header.isdigit() else expected_size
                downloaded = 0
                hasher = hashlib.sha256()

                with open(temp_path, "wb") as out_f:
                    while buffer := response.read(65536):
                        downloaded += len(buffer)
                        out_f.write(buffer)
                        hasher.update(buffer)
                        mb_down = downloaded / (1024 * 1024)
                        if total_size:
                            percent = (downloaded / total_size) * 100
                            mb_tot = total_size / (1024 * 1024)
                            sys.stdout.write(f"\r[DOWNLOADING] {mb_down:.2f}MB / {mb_tot:.2f}MB ({percent:.1f}%)")
                        else:
                            sys.stdout.write(f"\r[DOWNLOADING] {mb_down:.2f}MB")
                        sys.stdout.flush()

                print("")
                actual_sha256 = hasher.hexdigest()
                if expected_sha256 and actual_sha256 != expected_sha256:
                    print(f"[WARNING] Checksum mismatch from {url}. Expected: {expected_sha256}, got: {actual_sha256}")
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    continue

                if os.path.exists(destination):
                    os.remove(destination)
                os.rename(temp_path, destination)
                print(f"[SUCCESS] Verified SHA-256: {actual_sha256}")
                return True
        except Exception as exc:
            last_error = exc
            print(f"[WARNING] Failed downloading from {url}: {exc}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    raise RuntimeError(f"Failed to download file from all candidate URLs. Last error: {last_error}")


def download_model(
    model_name: str,
    output_dir: str | None = None,
    force: bool = False,
) -> str | dict[str, str]:
    """Download a registered model by name (or 'all')."""
    if output_dir is None:
        output_dir = DEFAULT_MODELS_DIR

    model_key = model_name.lower().strip()
    if model_key == "all":
        return {
            k: str(download_model(k, output_dir=output_dir, force=force))
            for k in sorted(MODELS.keys())
        }

    if model_key not in MODELS:
        raise ValueError(f"Unknown model '{model_name}'. Available: {list(MODELS.keys()) + ['all']}")

    info = MODELS[model_key]
    dest_path = os.path.join(output_dir, str(info["filename"]))

    if os.path.isfile(dest_path) and not force:
        print(f"[CHECK] Verifying existing model file: {dest_path}")
        existing_sha = compute_sha256(dest_path)
        if existing_sha == info["sha256"]:
            print(f"[INFO] Model '{model_key}' already exists and matches SHA-256 ({existing_sha}).")
            return dest_path
        print("[WARNING] Existing file checksum differs. Re-downloading...")

    print(f"[INFO] Downloading model '{model_key}': {info['description']}")
    download_file(
        urls=list(info["urls"]),  # type: ignore[arg-type]
        destination=dest_path,
        expected_sha256=str(info["sha256"]),
        expected_size=int(info["size_bytes"]),  # type: ignore[arg-type]
    )
    return dest_path


def ensure_model(model_name: str, output_dir: str | None = None) -> str | dict[str, str]:
    """Ensure the requested model is downloaded and ready for use."""
    return download_model(model_name, output_dir=output_dir, force=False)


def _inspect_single_model(
    model_key: str,
    meta: dict[str, object],
    target_dir: str,
    verify: bool,
) -> dict[str, object]:
    """Inspect presence, size, and optional SHA-256 hash of a single registered model."""
    filename = str(meta["filename"])
    dest = os.path.join(target_dir, filename)
    expected_sha = str(meta["sha256"])
    exists = os.path.isfile(dest)
    size_bytes = os.path.getsize(dest) if exists else 0
    actual_sha: str | None = None
    hash_match: bool | None = None
    if not exists:
        status = "missing"
    elif verify:
        actual_sha = compute_sha256(dest)
        hash_match = actual_sha.lower() == expected_sha.lower()
        status = "valid" if hash_match else "corrupt"
    else:
        status = "present"
    return {
        "name": model_key,
        "filename": filename,
        "path": dest,
        "description": str(meta.get("description", "")),
        "expected_size_bytes": int(meta.get("size_bytes", 0)),  # type: ignore[arg-type]
        "expected_sha256": expected_sha,
        "exists": exists,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024.0 * 1024.0), 2),
        "sha256": actual_sha,
        "hash_match": hash_match,
        "status": status,
    }


def _print_models_status(target_dir: str, entries: list[dict[str, object]]) -> None:
    """Print human-readable status summary for inspected ONNX models."""
    print("=" * 60)
    print(f"AI Model Weights Status ({target_dir})")
    print("=" * 60)
    for item in entries:
        key = str(item["name"])
        status = str(item["status"])
        if status == "missing":
            print(f"  [-] {key:<12}: MISSING ({item['filename']})")
        elif status == "valid":
            print(f"  [+] {key:<12}: VALID ({item['size_mb']:.2f} MB, SHA-256 OK)")
        elif status == "corrupt":
            exp = str(item["expected_sha256"])[:12]
            got = str(item["sha256"] or "")[:12]
            print(f"  [!] {key:<12}: CORRUPT (Hash mismatch: expected {exp}, got {got})")
        else:
            print(f"  [*] {key:<12}: PRESENT ({item['size_mb']:.2f} MB, unverified)")
    print("=" * 60)


def check_status(
    output_dir: str | None = None,
    *,
    verify: bool = True,
    quiet: bool = False,
    model_name: str | None = None,
) -> dict[str, object]:
    """Check presence and optional SHA-256 integrity of registered models."""
    target_dir = output_dir or DEFAULT_MODELS_DIR
    if model_name is not None:
        key = model_name.lower().strip()
        if key not in MODELS:
            raise ValueError(f"Unknown model '{model_name}'. Available: {list(MODELS.keys())}")
        selected = [(key, MODELS[key])]
    else:
        selected = list(MODELS.items())

    entries = [_inspect_single_model(k, meta, target_dir, verify) for k, meta in selected]
    counts = {
        "total": len(entries),
        "valid": sum(1 for item in entries if item["status"] == "valid"),
        "missing": sum(1 for item in entries if item["status"] == "missing"),
        "corrupt": sum(1 for item in entries if item["status"] == "corrupt"),
        "present": sum(1 for item in entries if item["status"] in ("valid", "present")),
    }
    if not quiet:
        _print_models_status(target_dir, entries)
    return {
        "models_dir": target_dir,
        "verified": verify,
        "all_valid": counts["valid"] == len(entries) and len(entries) > 0,
        "counts": counts,
        "models": entries,
    }
