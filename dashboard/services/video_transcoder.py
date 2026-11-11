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
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional
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

    @staticmethod
    def transcode_to_h264_async(
        input_path: str,
        output_path: str,
        target_resolution: Optional[str] = "1080p",
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        stop_event: Optional[threading.Event] = None,
        proc_holder: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Transcodes video asynchronously with realtime progress parsing from FFmpeg stdout.
        Supports cancellation via stop_event and cleans up partial output files.
        """
        stop_event = stop_event or threading.Event()
        meta = VideoTranscodeService.probe_video(input_path)
        total_duration = meta.get("duration", 0.0) or 0.0

        scale_filter = "scale='min(1920,iw)':-2"
        if target_resolution == "720p":
            scale_filter = "scale='min(1280,iw)':-2"

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-vf", scale_filter,
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            output_path,
        ]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        if proc_holder is not None:
            proc_holder["proc"] = proc

        stderr_lines: list[str] = []

        def _drain_stderr():
            if proc.stderr:
                for line in iter(proc.stderr.readline, ""):
                    if line:
                        stderr_lines.append(line)
                        if len(stderr_lines) > 50:
                            stderr_lines.pop(0)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        def _monitor_cancellation():
            while proc.poll() is None:
                if stop_event.is_set():
                    try:
                        proc.terminate()
                        for _ in range(20):
                            if proc.poll() is not None:
                                break
                            if stop_event.wait(0.1):
                                pass
                        if proc.poll() is None:
                            proc.kill()
                    except Exception:
                        pass
                    break
                stop_event.wait(0.2)

        cancel_thread = threading.Thread(target=_monitor_cancellation, daemon=True)
        cancel_thread.start()

        start_time = time.time()
        last_cb_time = 0.0
        current_metrics: Dict[str, Any] = {
            "percent": 0.0,
            "frame": 0,
            "fps": 0.0,
            "elapsed": 0.0,
            "out_time_sec": 0.0,
        }

        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    if not line:
                        break
                    line = line.strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip()
                        if k == "frame":
                            try:
                                current_metrics["frame"] = int(v)
                            except ValueError:
                                pass
                        elif k == "fps":
                            try:
                                current_metrics["fps"] = float(v)
                            except ValueError:
                                pass
                        elif k in ("out_time_us", "out_time_ms"):
                            try:
                                val = float(v)
                                sec = val / 1_000_000.0 if k == "out_time_us" else val / 1000.0
                                current_metrics["out_time_sec"] = sec
                                if total_duration > 0:
                                    current_metrics["percent"] = min(99.0, round((sec / total_duration) * 100, 1))
                            except ValueError:
                                pass
                        elif k == "progress" and v == "end":
                            current_metrics["percent"] = 100.0

                    now = time.time()
                    if progress_callback is not None and (now - last_cb_time >= 0.3 or current_metrics["percent"] >= 100.0):
                        last_cb_time = now
                        current_metrics["elapsed"] = round(now - start_time, 1)
                        try:
                            progress_callback(dict(current_metrics))
                        except Exception as cb_err:
                            logger.debug("Transcode progress callback error: %s", cb_err)

            proc.wait()
        finally:
            if proc.stdout:
                try:
                    proc.stdout.close()
                except Exception:
                    pass
            if proc.stderr:
                try:
                    proc.stderr.close()
                except Exception:
                    pass

        if stop_event is not None and stop_event.is_set():
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            raise RuntimeError("Transcoding was cancelled by user")

        if proc.returncode != 0:
            err_msg = "".join(stderr_lines)[-300:]
            logger.error("FFmpeg transcode async failed (code %s): %s", proc.returncode, err_msg)
            raise RuntimeError(f"FFmpeg transcode error: {err_msg}")

        if progress_callback is not None:
            current_metrics["percent"] = 100.0
            current_metrics["elapsed"] = round(time.time() - start_time, 1)
            try:
                progress_callback(dict(current_metrics))
            except Exception:
                pass

        return True

