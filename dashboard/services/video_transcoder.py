"""
Intelligent Tracker Dashboard - Video Probing & Transcoding Service.

Encapsulates ffprobe/OpenCV video stream metadata extraction and ffmpeg-based
H.264 web transcoding.
"""

from __future__ import annotations

import os
import json
import logging
import subprocess
from typing import Dict, Any, Optional

import cv2

logger = logging.getLogger("intelligent_tracker.dashboard.transcoder")


class VideoTranscodeService:
    """Provides video metadata probing and H.264 web-compatible transcoding."""

    @staticmethod
    def probe_video_file(path: str) -> Dict[str, Any]:
        """Inspect video file metadata and codec via ffprobe or cv2."""
        meta = {
            "codec": "unknown",
            "web_compatible": False,
            "width": 0,
            "height": 0,
            "fps": 0.0,
            "duration": 0.0,
            "frames": 0,
        }
        # 1. Try ffprobe for accurate codec identification (HEVC, H264, etc.)
        try:
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", "-show_format", path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3.0)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for s in data.get("streams", []):
                    if s.get("codec_type") == "video":
                        codec = s.get("codec_name", "").lower()
                        meta["codec"] = codec
                        meta["width"] = int(s.get("width", 0))
                        meta["height"] = int(s.get("height", 0))
                        meta["web_compatible"] = codec in ("h264", "avc1", "vp8", "vp9", "av1")
                        dur = s.get("duration") or data.get("format", {}).get("duration", 0)
                        meta["duration"] = round(float(dur), 2)
                        r_fps = s.get("r_frame_rate", "0/1")
                        if "/" in r_fps:
                            num, den = r_fps.split("/")
                            meta["fps"] = round(float(num) / float(den), 2) if float(den) > 0 else 0.0
                        return meta
        except Exception:
            pass

        # 2. Fallback to OpenCV VideoCapture
        try:
            cap = cv2.VideoCapture(path)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = float(cap.get(cv2.CAP_PROP_FPS))
                count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
                tag = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)]).lower()
                cap.release()
                meta["width"] = w
                meta["height"] = h
                meta["fps"] = round(fps, 2) if fps > 0 else 30.0
                meta["frames"] = count
                meta["duration"] = round(count / fps, 2) if (fps > 0 and count > 0) else 0.0
                meta["codec"] = tag if tag.strip() else "unknown"
                meta["web_compatible"] = tag in ("avc1", "h264") or path.lower().endswith(("_h264.mp4",))
        except Exception:
            pass
        return meta

    @staticmethod
    def transcode(
        input_path: str,
        output_path: str,
        target_resolution: Optional[str] = "1080p",
        timeout: float = 300.0,
    ) -> Dict[str, Any]:
        """
        Transcodes video to web-optimized H.264 MP4 with faststart flags.
        """
        scale_filter = "scale='min(1920,iw)':-2"
        if target_resolution == "720p":
            scale_filter = "scale='min(1280,iw)':-2"

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-vf", scale_filter,
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            output_path
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"Transcoding failed: {proc.stderr[-300:]}")

        stat = os.stat(output_path)
        return {
            "status": "success",
            "output_path": output_path,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
        }

