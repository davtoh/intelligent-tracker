"""Occurrence Analytics Reporting, Formatting, and CLI Helpers for Batch Indexing."""

import argparse
import csv
import json
import logging
import math
import os
import sys
import time
from typing import Any, Callable

import cv2

from intelligent_tracker.database import TrackerDB

logger = logging.getLogger(__name__)


def open_video_capture(video_path: str) -> tuple[cv2.VideoCapture, dict[str, Any]]:
    """Validate and open a recorded video file, returning capture and metadata."""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video file: {video_path}")
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    raw_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    fps = raw_fps if (math.isfinite(raw_fps) and raw_fps > 0.0) else 30.0
    meta = {
        "total_frames": total_frames, "fps": fps, "source_fps": round(fps, 4),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
        "duration_sec": total_frames / fps if fps > 0 else 0.0,
    }
    return cap, meta


def read_video_timestamp(cap: cv2.VideoCapture, read_frames: int, fps: float) -> float:
    """Resolve current frame media offset in seconds from container PTS or FPS."""
    pos_msec = cap.get(cv2.CAP_PROP_POS_MSEC)
    if pos_msec is not None and math.isfinite(pos_msec) and pos_msec > 0.0:
        return float(pos_msec) / 1000.0
    return (read_frames - 1) / fps


def record_step_occurrences(
    step_res: Any, state: dict[str, Any], read_frames: int, width: int, height: int, *, video_ts: float | None = None
) -> None:
    """Accumulate detection, identification, and overlay track records from a step."""
    state["total_detections"] += len(step_res.detections)
    if step_res.identifications:
        state["matched_identifications"] += len(step_res.identifications)
        for ev in step_res.identifications:
            if hasattr(ev, "entity_id"):
                state["identified_entities"].add(ev.entity_id)
    tracks = step_res.tracks
    track_objects = tracks.values() if isinstance(tracks, dict) else tracks
    active_tracks = [t.to_dict() for t in track_objects if hasattr(t, "to_dict")]
    if active_tracks:
        rel_time = float(video_ts) if video_ts is not None else float(step_res.timestamp)
        state["frame_detections"].append({
            "time": round(rel_time, 3), "frame": read_frames - 1,
            "source_resolution": [width, height], "tracks": active_tracks,
        })


def flush_meta(meta: dict[str, Any], state: dict[str, Any], latest_time: float, *, final: bool) -> dict[str, Any]:
    """Build metadata payload for progressive frame detection flushes."""
    return {
        "source_resolution": [meta["width"], meta["height"]],
        "source_fps": meta["source_fps"],
        "processed_frames": state["processed_frames"],
        "read_frames": state["read_frames"],
        "total_frames": meta["total_frames"],
        "latest_time": round(latest_time, 3),
        "cancelled": state["cancelled"] if final else False,
        "final": final,
    }


def write_stdout_progress(
    read_frames: int, total: int, processed: int, state: dict[str, Any], now: float
) -> None:
    """Write inline CLI indexing progress."""
    pct = (read_frames / total * 100.0) if total > 0 else 0.0
    elapsed = max(1e-4, now - state["start_wall_time"])
    sys.stdout.write(
        f"\r[INDEXING] Frame {read_frames}/{total} ({pct:.1f}%) | "
        f"Speed: {processed / elapsed:.1f} FPS | Sightings: {state['matched_identifications']}"
    )
    sys.stdout.flush()


def emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    state: dict[str, Any],
    meta: dict[str, Any],
    verbose: bool,
    *,
    final: bool = False,
) -> None:
    """Emit throttled or final progress updates to callback and optional stdout."""
    now = time.time()
    read_frames, processed, total = state["read_frames"], state["processed_frames"], meta["total_frames"]
    if not final and read_frames % 10 != 0 and (now - state["last_cb_time"]) < 0.25:
        if verbose and processed % 20 == 0:
            write_stdout_progress(read_frames, total, processed, state, now)
        return
    state["last_cb_time"] = now
    elapsed = max(1e-4, now - state["start_wall_time"])
    pct = 100.0 if (final and not state["cancelled"] and read_frames >= total > 0) else (
        (read_frames / total * 100.0) if total > 0 else 0.0
    )
    if progress_callback is not None:
        payload = {
            "read_frames": read_frames, "total_frames": total, "processed_frames": processed,
            "percent": round(pct, 1), "fps": round(processed / elapsed, 1),
            "sightings": state["matched_identifications"], "elapsed": round(elapsed, 1),
        }
        if final:
            payload["cancelled"] = state["cancelled"]
        try:
            progress_callback(payload)
        except Exception as cb_err:
            logger.debug("Progress callback error: %s", cb_err)
    if verbose and not final and processed % 20 == 0:
        write_stdout_progress(read_frames, total, processed, state, now)


def build_final_report(
    video_path: str, source_name: str, meta: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Assemble final batch indexing summary dictionary."""
    elapsed = time.time() - state["start_wall_time"]
    return {
        "video_path": video_path, "source": source_name,
        "source_resolution": [meta["width"], meta["height"]], "source_fps": meta["source_fps"],
        "total_frames_in_file": meta["total_frames"], "read_frames": state["read_frames"],
        "processed_frames": state["processed_frames"], "elapsed_seconds": round(elapsed, 2),
        "video_duration_seconds": round(meta["duration_sec"], 2),
        "total_detections": state["total_detections"],
        "identifications_count": state["matched_identifications"],
        "unique_entities_identified": list(state["identified_entities"]),
        "cancelled": state["cancelled"], "frame_detections": state["frame_detections"],
    }


def format_occurrence_report(
    db: TrackerDB,
    entity_id: int | None = None,
    source: str | None = None,
    video_filename: str | None = None,
) -> dict[str, Any]:
    """Generate occurrence analytics and sighting timelines across entities."""
    sightings = db.get_sightings(
        entity_id=entity_id, source=source, limit=0, video_filename=video_filename
    )
    if entity_id is not None:
        entity_analytics = [db.get_entity_analytics(entity_id, video_filename=video_filename)]
    else:
        seen_ids = {s["entity_id"] for s in sightings if s.get("entity_id") is not None} if video_filename else None
        entities = db.list_entities()
        entity_analytics = [
            db.get_entity_analytics(e["id"], video_filename=video_filename)
            for e in entities
            if seen_ids is None or e["id"] in seen_ids
        ]

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "total_sightings": len(sightings),
        "entities_analyzed": len(entity_analytics),
        "entities": entity_analytics,
    }


def _print_entity_row(ent_data: dict[str, Any]) -> None:
    """Print a single entity analytics row and its recent timeline tail."""
    ent = ent_data.get("entity", {})
    eid = ent.get("id", "-")
    name = (ent.get("name") or "Unknown")[:17]
    cat = (ent.get("category") or "person")[:11]
    sightings_count = ent_data.get("total_sightings", 0)
    dwell = f"{ent_data.get('estimated_dwell_seconds', 0.0):.1f}s"
    sources_count = ent_data.get("distinct_sources_count", 0)
    print(f"{eid:<5} {name:<18} {cat:<12} {sightings_count:<10} {dwell:<12} {sources_count:<10}")

    timeline = ent_data.get("timeline", [])
    if timeline:
        print(f"      Timeline (last {min(3, len(timeline))} events):")
        for ev in timeline[-3:]:
            zone = ev.get("zone_id") or "open"
            conf = ev.get("confidence", 0.0)
            print(f"        - [{ev.get('timestamp')}] Source: '{ev.get('source')}' | Zone: '{zone}' | Conf: {conf:.2f}")


def print_occurrence_report(report: dict[str, Any]) -> None:
    """Format and print an occurrence analytics summary table to stdout."""
    print("\n" + "=" * 75)
    print("OCCURRENCE & RE-IDENTIFICATION ANALYTICS REPORT")
    print(f"Generated: {report.get('generated_at', 'N/A')}")
    print("=" * 75)

    entities = report.get("entities", [])
    if not entities:
        print("  No entity sightings recorded yet.")
        print("=" * 75)
        return

    print(f"{'ID':<5} {'Name':<18} {'Category':<12} {'Sightings':<10} {'Dwell Est.':<12} {'Sources':<10}")
    print("-" * 75)
    for ent_data in entities:
        _print_entity_row(ent_data)
    print("=" * 75)


def _export_csv_report(report: dict[str, Any], csv_path: str) -> None:
    """Write occurrence report summary rows to a CSV file."""
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)) or ".", exist_ok=True)
    fieldnames = [
        "entity_id", "name", "category", "total_sightings",
        "first_seen", "last_seen", "dwell_seconds", "sources", "zones",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in report.get("entities", []):
            ent = entry.get("entity", {})
            writer.writerow({
                "entity_id": ent.get("id"),
                "name": ent.get("name"),
                "category": ent.get("category"),
                "total_sightings": entry.get("total_sightings", 0),
                "first_seen": entry.get("first_seen", ""),
                "last_seen": entry.get("last_seen", ""),
                "dwell_seconds": entry.get("estimated_dwell_seconds", 0.0),
                "sources": "; ".join(entry.get("sources", [])),
                "zones": "; ".join(entry.get("zones", [])),
            })
    print(f"[INFO] Exported occurrence report CSV -> {csv_path}")


def export_occurrence_report(
    report: dict[str, Any],
    json_path: str | None = None,
    csv_path: str | None = None,
) -> None:
    """Export occurrence report to JSON and/or CSV files."""
    if json_path:
        os.makedirs(os.path.dirname(os.path.abspath(json_path)) or ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"[INFO] Exported occurrence report JSON -> {json_path}")

    if csv_path:
        _export_csv_report(report, csv_path)


def build_batch_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for offline batch video indexing."""
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
    return parser


def run_batch_cli(argv: list[str] | None = None) -> int:
    """Execute the standalone batch indexing CLI entrypoint."""
    from intelligent_tracker.batch import VideoIndexer

    args = build_batch_arg_parser().parse_args(argv)
    indexer = VideoIndexer(
        db_path=args.db,
        detector_name=args.detector,
        reid_name=args.reid,
        reid_threshold=args.reid_thresh,
        sample_rate=args.sample_rate,
    )
    try:
        if args.video:
            indexer.process_video(args.video, max_frames=args.max_frames)
        if args.report or args.export_json or args.export_csv or not args.video:
            rep = indexer.generate_occurrence_report()
            indexer.print_report(rep)
            indexer.export_report(rep, json_path=args.export_json, csv_path=args.export_csv)
    finally:
        indexer.close()
    return 0
