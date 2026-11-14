#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Offline Video Recording Indexer & Occurrence Analytics Module.

Provides:

- Fast-forward and sampled frame rate batch ingestion for recorded video files (.mp4, .avi, .mkv).
- Automated object detection, tracking, feature extraction, Re-ID gallery matching,
  and audit trail logging into SQLite TrackerDB.
- Occurrence Analytics:

  - Chronological Sighting Timelines per entity.
  - Visit frequency, first seen, last seen, and dwell duration estimates.
  - Spatial zone journeys across monitored regions.
  - Formatted terminal report and JSON/CSV export.

- Standalone CLI execution (``python -m intelligent_tracker.batch``).
"""

import os
import sys
import time
import math
import json
import csv
import argparse
import logging
import threading
from typing import Dict, List, Optional, Any, Callable

import cv2

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import ReIDExtractorFactory
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.tracker import TrackerFactory
from intelligent_tracker.detectors import DetectorFactory
from intelligent_tracker.analytics import AnalyticsEngine

logger = logging.getLogger(__name__)


def _dispatch_frame_flush(
    callback: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any]], None]],
    frame_detections: List[Dict[str, Any]],
    last_flushed_idx: int,
    meta: Dict[str, Any],
) -> int:
    """Emit newly collected frame detections to a progressive stream listener."""
    if callback is None:
        return last_flushed_idx
    chunk = list(frame_detections[last_flushed_idx:])
    try:
        callback(chunk, meta)
    except Exception as cb_err:
        logger.debug("Frame flush callback error: %s", cb_err)
    return len(frame_detections)


class VideoIndexer:
    """
    Offline batch video processor and occurrence analytics indexer.
    """

    def __init__(
        self,
        db: Optional[TrackerDB] = None,
        db_path: str = "data/tracker.db",
        detector_name: str = "yolov8",
        reid_name: str = "color",
        reid_threshold: float = 0.65,
        tracker_type: str = "centroid",
        sample_rate: int = 1,
        conf_threshold: float = 0.25,
        classes: Optional[List[str]] = None,
        analytics: Optional[AnalyticsEngine] = None,
    ):
        self.db = db if db is not None else TrackerDB(db_path)
        self.sample_rate = max(1, int(sample_rate))

        # Initialize detector
        det_kwargs = {}
        det_name_clean = str(detector_name).lower().strip()
        if det_name_clean in ("yolov8", "yolov8n", "yolo11", "yolo11n", "onnx"):
            det_kwargs["conf_threshold"] = conf_threshold
            if classes:
                det_kwargs["classes"] = classes
        elif det_name_clean in ("mock", "mockdetector"):
            det_kwargs["confidence"] = conf_threshold
        self.detector = DetectorFactory.create(detector_name, **det_kwargs)

        # Initialize tracker
        self.tracker = TrackerFactory.create(tracker_type)

        # Initialize Re-ID feature extractor & gallery matcher
        self.extractor = ReIDExtractorFactory.create(reid_name)
        self.matcher = GalleryMatcher(
            db=self.db,
            extractor=self.extractor,
            reid_threshold=reid_threshold,
            sighting_interval=1.0,  # Finer debounce for offline video
        )

        self.analytics = analytics

    def process_video(
        self,
        video_path: str,
        source_label: Optional[str] = None,
        max_frames: int = 0,
        verbose: bool = True,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        stop_event: Optional[threading.Event] = None,
        frame_flush_callback: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any]], None]] = None,
        flush_interval: int = 30,
    ) -> Dict[str, Any]:
        """
        Process a recorded video file, catalog occurrences into TrackerDB,
        and return execution summary.

        :param video_path: Path to recorded video file.
        :param source_label: Custom name for the video source (defaults to filename).
        :param max_frames: Max frames to process (0 = whole video).
        :param verbose: Print progress to stdout.
        :param progress_callback: Optional callback receiving progress dict.
        :param stop_event: Optional threading.Event to interrupt indexing early.
        :param frame_flush_callback: Optional callback receiving (chunk, meta) periodically.
        :param flush_interval: Processed frame interval for progressive flushes (default 30).
        :return: Execution summary dictionary.
        """
        if not os.path.isfile(video_path):
            raise FileNotFoundError("Video file not found: {}".format(video_path))

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError("Failed to open video file: {}".format(video_path))

        source_name = source_label or os.path.basename(video_path)
        total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        raw_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        fps = raw_fps if (math.isfinite(raw_fps) and raw_fps > 0.0) else 30.0
        source_fps = round(fps, 4)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration_sec = total_video_frames / fps if fps > 0 else 0.0

        if verbose:
            print("=" * 65)
            print("Indexing Video: {}".format(video_path))
            print("  Total Frames : {} (~{:.1f}s at {:.1f} FPS)".format(total_video_frames, duration_sec, fps))
            print("  Resolution   : {}x{}".format(width, height))
            print("  Sample Rate  : Process every {} frame(s)".format(self.sample_rate))
            print("  Gallery Size : {} enrolled signatures".format(self.matcher.gallery_size))
            print("=" * 65)

        processed_frames = 0
        read_frames = 0
        total_detections_count = 0
        matched_identifications = 0
        identified_entities = set()
        cancelled = False
        start_wall_time = time.time()
        last_cb_time = 0.0
        frame_detections: List[Dict[str, Any]] = []
        last_flushed_idx = 0
        last_video_timestamp = 0.0
        flush_step = max(1, int(flush_interval))

        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    cancelled = True
                    break

                ret, frame = cap.read()
                if not ret or frame is None:
                    break

                if (width <= 0 or height <= 0) and hasattr(frame, "shape"):
                    height, width = int(frame.shape[0]), int(frame.shape[1])

                read_frames += 1
                if max_frames > 0 and read_frames > max_frames:
                    break

                # Sample frames for fast-forward indexing
                if (read_frames - 1) % self.sample_rate != 0:
                    continue

                processed_frames += 1
                pos_msec = cap.get(cv2.CAP_PROP_POS_MSEC)
                if pos_msec is not None and math.isfinite(pos_msec) and pos_msec > 0.0:
                    video_timestamp = pos_msec / 1000.0
                else:
                    video_timestamp = (read_frames - 1) / fps
                last_video_timestamp = video_timestamp

                # 1. Detect
                detections = self.detector.detect(frame)
                if detections:
                    total_detections_count += len(detections)

                # 2. Track
                tracks = self.tracker.update(detections, timestamp=video_timestamp)

                # 3. Match against Re-ID Gallery
                events = self.matcher.match_tracks(
                    tracks=tracks,
                    frame=frame,
                    source=source_name,
                    timestamp=video_timestamp,
                )

                if events:
                    matched_identifications += len(events)
                    for ev in events:
                        identified_entities.add(ev.entity_id)

                # Record frame-indexed active tracks for video overlay
                track_objects = tracks.values() if isinstance(tracks, dict) else tracks
                active_tracks = [t.to_dict() for t in track_objects if hasattr(t, "to_dict")]
                if active_tracks:
                    frame_detections.append({
                        "time": round(video_timestamp, 3),
                        "frame": read_frames - 1,
                        "source_resolution": [width, height],
                        "tracks": active_tracks,
                    })

                # 4. Optional Spatial Analytics
                if self.analytics is not None:
                    self.analytics.update(tracks, timestamp=video_timestamp)

                # 5. Progressive Detection Chunk Flush (every flush_step processed frames)
                if frame_flush_callback is not None and processed_frames % flush_step == 0:
                    last_flushed_idx = _dispatch_frame_flush(
                        frame_flush_callback,
                        frame_detections,
                        last_flushed_idx,
                        {
                            "source_resolution": [width, height],
                            "source_fps": source_fps,
                            "processed_frames": processed_frames,
                            "read_frames": read_frames,
                            "total_frames": total_video_frames,
                            "latest_time": round(video_timestamp, 3),
                            "cancelled": False,
                            "final": False,
                        },
                    )

                # Progress reporting via callback or stdout
                now = time.time()
                if (read_frames % 10 == 0 or (now - last_cb_time) >= 0.25):
                    last_cb_time = now
                    pct = (read_frames / total_video_frames * 100) if total_video_frames > 0 else 0.0
                    elapsed = now - start_wall_time
                    fps_eff = processed_frames / elapsed if elapsed > 0 else 0.0
                    if progress_callback is not None:
                        try:
                            progress_callback({
                                "read_frames": read_frames,
                                "total_frames": total_video_frames,
                                "processed_frames": processed_frames,
                                "percent": round(pct, 1),
                                "fps": round(fps_eff, 1),
                                "sightings": matched_identifications,
                                "elapsed": round(elapsed, 1),
                            })
                        except Exception as cb_err:
                            logger.debug("Progress callback error: %s", cb_err)

                if verbose and processed_frames % 20 == 0:
                    pct = (read_frames / total_video_frames * 100) if total_video_frames > 0 else 0
                    elapsed = time.time() - start_wall_time
                    fps_eff = processed_frames / elapsed if elapsed > 0 else 0
                    sys.stdout.write(
                        "\r[INDEXING] Frame {}/{} ({:.1f}%) | Speed: {:.1f} FPS | Sightings: {}".format(
                            read_frames, total_video_frames, pct, fps_eff, matched_identifications
                        )
                    )
                    sys.stdout.flush()

        finally:
            cap.release()
            del cap

        elapsed_wall_time = time.time() - start_wall_time
        final_pct = 100.0 if (not cancelled and read_frames >= total_video_frames and total_video_frames > 0) else (
            (read_frames / total_video_frames * 100) if total_video_frames > 0 else 0.0
        )
        if progress_callback is not None:
            try:
                progress_callback({
                    "read_frames": read_frames,
                    "total_frames": total_video_frames,
                    "processed_frames": processed_frames,
                    "percent": round(final_pct, 1),
                    "fps": round(processed_frames / max(1e-4, elapsed_wall_time), 1),
                    "sightings": matched_identifications,
                    "elapsed": round(elapsed_wall_time, 1),
                    "cancelled": cancelled,
                })
            except Exception as cb_err:
                logger.debug("Final progress callback error: %s", cb_err)

        if frame_flush_callback is not None:
            last_flushed_idx = _dispatch_frame_flush(
                frame_flush_callback,
                frame_detections,
                last_flushed_idx,
                {
                    "source_resolution": [width, height],
                    "source_fps": source_fps,
                    "processed_frames": processed_frames,
                    "read_frames": read_frames,
                    "total_frames": total_video_frames,
                    "latest_time": round(last_video_timestamp, 3),
                    "cancelled": cancelled,
                    "final": True,
                },
            )

        if verbose:
            tag = "[CANCELLED]" if cancelled else "[COMPLETED]"
            print("\n{} Indexed {} frames in {:.2f}s ({:.1f} FPS)".format(
                tag, processed_frames, elapsed_wall_time, processed_frames / max(1e-4, elapsed_wall_time)
            ))

        return {
            "video_path": video_path,
            "source": source_name,
            "source_resolution": [width, height],
            "source_fps": source_fps,
            "total_frames_in_file": total_video_frames,
            "read_frames": read_frames,
            "processed_frames": processed_frames,
            "elapsed_seconds": round(elapsed_wall_time, 2),
            "video_duration_seconds": round(duration_sec, 2),
            "total_detections": total_detections_count,
            "identifications_count": matched_identifications,
            "unique_entities_identified": list(identified_entities),
            "cancelled": cancelled,
            "frame_detections": frame_detections,
        }

    def generate_occurrence_report(
        self,
        entity_id: Optional[int] = None,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate occurrence analytics and sighting timelines across all or specific entities.
        """
        if entity_id is not None:
            entity_analytics = [self.db.get_entity_analytics(entity_id)]
        else:
            entities = self.db.list_entities()
            entity_analytics = [self.db.get_entity_analytics(e["id"]) for e in entities]

        # Overall summary
        sightings = self.db.get_sightings(entity_id=entity_id, source=source, limit=0)

        report = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            "total_sightings": len(sightings),
            "entities_analyzed": len(entity_analytics),
            "entities": entity_analytics,
        }
        return report

    def print_report(self, report: Dict[str, Any]):
        """Format and print an occurrence analytics summary table to the console."""
        print("\n" + "=" * 75)
        print("OCCURRENCE & RE-IDENTIFICATION ANALYTICS REPORT")
        print("Generated: {}".format(report.get("generated_at", "N/A")))
        print("=" * 75)

        entities = report.get("entities", [])
        if not entities:
            print("  No entity sightings recorded yet.")
            print("=" * 75)
            return

        header = "{:<5} {:<18} {:<12} {:<10} {:<12} {:<10}".format(
            "ID", "Name", "Category", "Sightings", "Dwell Est.", "Sources"
        )
        print(header)
        print("-" * 75)

        for ent_data in entities:
            ent = ent_data.get("entity", {})
            eid = ent.get("id", "-")
            name = (ent.get("name") or "Unknown")[:17]
            cat = (ent.get("category") or "person")[:11]
            sightings_count = ent_data.get("total_sightings", 0)
            dwell = "{:.1f}s".format(ent_data.get("estimated_dwell_seconds", 0.0))
            sources_count = ent_data.get("distinct_sources_count", 0)

            row = "{:<5} {:<18} {:<12} {:<10} {:<12} {:<10}".format(
                eid, name, cat, sightings_count, dwell, sources_count
            )
            print(row)

            # Print timeline sample if available
            timeline = ent_data.get("timeline", [])
            if timeline:
                print("      Timeline (last {} events):".format(min(3, len(timeline))))
                for ev in timeline[-3:]:
                    print("        - [{}] Source: '{}' | Zone: '{}' | Conf: {:.2f}".format(
                        ev.get("timestamp"), ev.get("source"), ev.get("zone_id") or "open", ev.get("confidence", 0.0)
                    ))
        print("=" * 75)

    def export_report(
        self,
        report: Dict[str, Any],
        json_path: Optional[str] = None,
        csv_path: Optional[str] = None,
    ):
        """Export occurrence report to JSON or CSV."""
        if json_path:
            os.makedirs(os.path.dirname(os.path.abspath(json_path)) or ".", exist_ok=True)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, default=str)
            print("[INFO] Exported occurrence report JSON -> {}".format(json_path))

        if csv_path:
            os.makedirs(os.path.dirname(os.path.abspath(csv_path)) or ".", exist_ok=True)
            fieldnames = ["entity_id", "name", "category", "total_sightings", "first_seen", "last_seen", "dwell_seconds", "sources", "zones"]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for e in report.get("entities", []):
                    ent = e.get("entity", {})
                    writer.writerow({
                        "entity_id": ent.get("id"),
                        "name": ent.get("name"),
                        "category": ent.get("category"),
                        "total_sightings": e.get("total_sightings", 0),
                        "first_seen": e.get("first_seen", ""),
                        "last_seen": e.get("last_seen", ""),
                        "dwell_seconds": e.get("estimated_dwell_seconds", 0.0),
                        "sources": "; ".join(e.get("sources", [])),
                        "zones": "; ".join(e.get("zones", [])),
                    })
            print("[INFO] Exported occurrence report CSV -> {}".format(csv_path))


def main():
    parser = argparse.ArgumentParser(description="Offline Video Recording Indexer & Occurrence Analytics")
    parser.add_argument("--video", default=None, help="Path to video file (.mp4, .avi, etc.) to index")
    parser.add_argument("--db", default="data/tracker.db", help="Path to SQLite database")
    parser.add_argument("--detector", default="yolov8", choices=["haar", "yolov8", "yolo11", "mock"], help="Detector backend")
    parser.add_argument("--reid", default="color", choices=["color", "onnx", "mock"], help="Re-ID extractor")
    parser.add_argument("--reid-thresh", type=float, default=0.65, help="Re-ID similarity threshold")
    parser.add_argument("--sample-rate", type=int, default=1, help="Process every Nth frame for fast indexing")
    parser.add_argument("--max-frames", type=int, default=0, help="Maximum frames to process (0 = all)")
    parser.add_argument("--report", action="store_true", help="Print occurrence analytics report after processing")
    parser.add_argument("--export-json", default=None, help="Export report to JSON file")
    parser.add_argument("--export-csv", default=None, help="Export report to CSV file")
    args = parser.parse_args()

    indexer = VideoIndexer(
        db_path=args.db,
        detector_name=args.detector,
        reid_name=args.reid,
        reid_threshold=args.reid_thresh,
        sample_rate=args.sample_rate,
    )

    if args.video:
        indexer.process_video(args.video, max_frames=args.max_frames)

    if args.report or args.export_json or args.export_csv or not args.video:
        rep = indexer.generate_occurrence_report()
        indexer.print_report(rep)
        indexer.export_report(rep, json_path=args.export_json, csv_path=args.export_csv)

    indexer.db.close()


if __name__ == "__main__":
    main()
