#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Video Transcoder Service.
Probes video codec metadata via ffprobe and transcodes non-browser formats
(HEVC, AVI, MKV) to web-optimized H.264 MP4 streams.
"""

import json
import logging
import os
import subprocess
from typing import Any, Dict, Optional
import cv2

logger = logging.getLogger(__name__)


class VideoTranscodeService:
    """
    Subprocess-driven video inspection and transcoding service.
    Converts security footage into browser-compatible H.264/AAC formats.
    """

    @staticmethod
    def probe_video(path: str) -> Dict[str, Any]:
        """Inspect video file metadata, resolution, duration, and codec compatibility."""
        meta: Dict[str, Any] = {
            "codec": "unknown",
            "web_compatible": False,
            "width": 0,
            "height": 0,
            "fps": 0.0,
            "duration": 0.0,
            "frames": 0,
        }
        # 1. Primary probe via ffprobe JSON output
        try:
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", "-show_format", path,
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
        except Exception as e:
            logger.debug("ffprobe probe failed for %s: %s", path, e)

        # 2. Secondary fallback via OpenCV VideoCapture
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
        except Exception as e:
            logger.debug("OpenCV probe fallback failed for %s: %s", path, e)

        return meta

    @staticmethod
    def transcode_to_h264(
        input_path: str,
        output_path: str,
        target_resolution: Optional[str] = "1080p",
        timeout: float = 300.0,
    ) -> bool:
        """Transcodes a video file to H.264/AAC with faststart for streaming."""
        scale_filter = "scale='min(1920,iw)':-2"
        if target_resolution == "720p":
            scale_filter = "scale='min(1280,iw)':-2"

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-vf", scale_filter,
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            logger.error("FFmpeg transcode failed: %s", proc.stderr)
            raise RuntimeError(f"FFmpeg transcode error: {proc.stderr[-300:]}")
        return True

