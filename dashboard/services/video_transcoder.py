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
from typing import Any, Callable
import cv2

logger = logging.getLogger(__name__)


def _build_staging_path(output_path: str) -> str:
    """Return transactional temporary staging path preserving the .mp4 muxer extension."""
    return f"{output_path}.part.mp4"


def _cleanup_staging_file(staging_path: str) -> None:
    """Best-effort removal of transient transcode staging files without touching target output."""
    if staging_path and os.path.exists(staging_path):
        try:
            os.remove(staging_path)
        except OSError as err:
            logger.debug("Could not remove staging transcode file %s: %s", staging_path, err)


def _promote_staging_file(staging_path: str, output_path: str) -> None:
    """Atomically promote a verified non-empty staging transcode into the final destination."""
    if not os.path.isfile(staging_path) or os.path.getsize(staging_path) <= 0:
        _cleanup_staging_file(staging_path)
        raise RuntimeError("FFmpeg produced an empty or missing transcode output file")
    os.replace(staging_path, output_path)


def _build_ffmpeg_command(
    input_path: str,
    target_path: str,
    target_resolution: str | None = "1080p",
    with_progress: bool = False,
) -> list[str]:
    """Construct FFmpeg H.264/AAC faststart command targeting the given destination path."""
    scale_filter = "scale='min(1280,iw)':-2" if target_resolution == "720p" else "scale='min(1920,iw)':-2"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-vf", scale_filter,
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
    ]
    if with_progress:
        cmd.extend(["-progress", "pipe:1", "-nostats"])
    cmd.append(target_path)
    return cmd


def _parse_ffmpeg_progress_line(
    line: str,
    current_metrics: dict[str, Any],
    total_duration: float,
) -> None:
    """Update progress metrics dictionary from a single FFmpeg `-progress` key=value line."""
    if "=" not in line:
        return
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
            # In FFmpeg -progress output, out_time_ms is emitted in microseconds despite its name.
            sec = float(v) / 1_000_000.0
            current_metrics["out_time_sec"] = sec
            if total_duration > 0:
                current_metrics["percent"] = min(99.0, round((sec / total_duration) * 100, 1))
        except ValueError:
            pass
    elif k == "progress" and v == "end":
        current_metrics["percent"] = 100.0


class VideoTranscodeService:
    """
    Subprocess-driven video inspection and transcoding service.
    Converts security footage into browser-compatible H.264/AAC formats.
    """

    @staticmethod
    def get_h264_pair_info(video_path: str) -> dict[str, Any]:
        """Return canonical _h264.mp4 output target and whether a valid paired copy exists."""
        directory = os.path.dirname(video_path)
        filename = os.path.basename(video_path)
        base_name, _ = os.path.splitext(filename)
        converted_filename = f"{base_name}_h264.mp4"
        converted_path = os.path.join(directory, converted_filename)
        exists = (
            not base_name.lower().endswith("_h264")
            and os.path.isfile(converted_path)
            and os.path.getsize(converted_path) > 0
        )
        return {
            "has_converted_h264": exists,
            "converted_filename": converted_filename if exists else None,
            "output_filename": converted_filename,
            "output_path": converted_path,
        }

    @staticmethod
    def probe_video(path: str) -> dict[str, Any]:
        """Inspect video file metadata, resolution, duration, and codec compatibility."""
        meta: dict[str, Any] = {
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
        target_resolution: str | None = "1080p",
        timeout: float = 300.0,
    ) -> bool:
        """Transcode a video to H.264/AAC via staging file, atomically promoting only on success."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        staging_path = _build_staging_path(output_path)
        _cleanup_staging_file(staging_path)
        cmd = _build_ffmpeg_command(input_path, staging_path, target_resolution, with_progress=False)

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if proc.returncode != 0:
                logger.error("FFmpeg transcode failed: %s", proc.stderr)
                raise RuntimeError(f"FFmpeg transcode error: {proc.stderr[-300:]}")
            _promote_staging_file(staging_path, output_path)
            return True
        except BaseException:
            _cleanup_staging_file(staging_path)
            raise

    @staticmethod
    def _monitor_ffmpeg_cancellation(
        proc: subprocess.Popen[str],
        stop_event: threading.Event,
        done_event: threading.Event,
    ) -> None:
        """Terminate FFmpeg cleanly when stop_event is triggered before process completion."""
        while proc.poll() is None and not done_event.is_set():
            if stop_event.is_set():
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                except Exception:
                    pass
                break
            stop_event.wait(0.2)

    @staticmethod
    def _stream_ffmpeg_progress(
        proc: subprocess.Popen[str],
        total_duration: float,
        progress_callback: Callable[[dict[str, Any]], None] | None,
    ) -> dict[str, Any]:
        """Parse FFmpeg progress pipe output and emit throttled progress updates."""
        start_time = time.time()
        last_cb_time = 0.0
        metrics: dict[str, Any] = {"percent": 0.0, "frame": 0, "fps": 0.0, "elapsed": 0.0, "out_time_sec": 0.0}
        if proc.stdout:
            for raw_line in iter(proc.stdout.readline, ""):
                if not raw_line:
                    break
                _parse_ffmpeg_progress_line(raw_line.strip(), metrics, total_duration)
                now = time.time()
                if progress_callback is not None and (now - last_cb_time >= 0.3 or metrics["percent"] >= 100.0):
                    last_cb_time = now
                    metrics["elapsed"] = round(now - start_time, 1)
                    try:
                        progress_callback(dict(metrics))
                    except Exception as cb_err:
                        logger.debug("Transcode progress callback error: %s", cb_err)
        proc.wait()
        metrics["elapsed"] = round(time.time() - start_time, 1)
        return metrics

    @staticmethod
    def transcode_to_h264_async(
        input_path: str,
        output_path: str,
        target_resolution: str | None = "1080p",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        stop_event: threading.Event | None = None,
        proc_holder: dict[str, Any] | None = None,
    ) -> bool:
        """
        Transcode asynchronously into a staging `.part.mp4` file and atomically replace
        `output_path` only on verified completion; cancellation/error preserves any prior output.
        """
        stop_event = stop_event or threading.Event()
        if stop_event.is_set():
            raise RuntimeError("Transcoding was cancelled by user")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        staging_path = _build_staging_path(output_path)
        _cleanup_staging_file(staging_path)

        total_duration = VideoTranscodeService.probe_video(input_path).get("duration", 0.0) or 0.0
        cmd = _build_ffmpeg_command(input_path, staging_path, target_resolution, with_progress=True)
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, creationflags=creationflags
        )
        if proc_holder is not None:
            proc_holder["proc"] = proc

        stderr_lines: list[str] = []
        done_event = threading.Event()

        def _drain_stderr() -> None:
            if proc.stderr:
                for line in iter(proc.stderr.readline, ""):
                    if line:
                        stderr_lines.append(line)
                        if len(stderr_lines) > 50:
                            stderr_lines.pop(0)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        cancel_thread = threading.Thread(
            target=VideoTranscodeService._monitor_ffmpeg_cancellation, args=(proc, stop_event, done_event), daemon=True
        )
        stderr_thread.start()
        cancel_thread.start()

        try:
            current_metrics = VideoTranscodeService._stream_ffmpeg_progress(proc, total_duration, progress_callback)
            done_event.set()
            stderr_thread.join(timeout=1.0)
            if stop_event.is_set():
                raise RuntimeError("Transcoding was cancelled by user")
            if proc.returncode != 0:
                err_msg = "".join(stderr_lines)[-300:]
                logger.error("FFmpeg transcode async failed (code %s): %s", proc.returncode, err_msg)
                raise RuntimeError(f"FFmpeg transcode error: {err_msg}")
            _promote_staging_file(staging_path, output_path)
        except BaseException:
            done_event.set()
            if proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
            _cleanup_staging_file(staging_path)
            raise
        finally:
            done_event.set()
            for pipe in (proc.stdout, proc.stderr):
                if pipe:
                    try:
                        pipe.close()
                    except Exception:
                        pass

        if progress_callback is not None:
            current_metrics["percent"] = 100.0
            try:
                progress_callback(dict(current_metrics))
            except Exception:
                pass
        return True

