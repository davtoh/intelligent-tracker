"""CLI `world` and `models` subcommands for `intelligent-tracker-ctl`."""

import argparse
import json
import os
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from intelligent_tracker.cli.arguments import load_config
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors.model_loader import check_status, download_model
from intelligent_tracker.memory import ConfidenceEngine
from intelligent_tracker.pipeline._world_setup import register_world_children
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.world import CameraNode, WorldEntity, WorldGraph


def add_world_and_models_subparsers(subparsers: Any) -> None:
    """Register `world` and `models` subcommands on the ctl parser."""
    world_p = subparsers.add_parser("world", help="Inspect live or offline WorldGraph topology and entities")
    world_p.add_argument("action", nargs="?", choices=["summary", "entities", "snapshot"], default="summary")
    world_p.add_argument("--camera", dest="camera_id", default=None, help="Filter entities by camera ID")
    world_p.add_argument("--min-confidence", type=float, default=None, help="Minimum confidence filter (0.0-1.0)")
    world_p.add_argument("--config", default=None, help="Offline YAML/JSON config or cameras.json path")
    world_p.add_argument("--db", default=None, help="Offline SQLite TrackerDB path")
    world_p.add_argument("--offline", action="store_true", help="Force offline inspection")
    world_p.add_argument("--url", dest="sub_url", default=None, help="Override dashboard API URL")
    world_p.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")

    models_p = subparsers.add_parser("models", help="Inspect, verify, or download ONNX model weights")
    models_p.add_argument("action", nargs="?", choices=["status", "verify", "download"], default="status")
    models_p.add_argument("--verify", action="store_true", help="Verify SHA-256 checksums")
    models_p.add_argument("--download", nargs="?", const="all", default=None, help="Download model locally (or 'all')")
    models_p.add_argument("--models-dir", default=None, help="Local ONNX models directory")
    models_p.add_argument("--force", action="store_true", help="Force re-download when downloading")
    models_p.add_argument("--offline", action="store_true", help="Force local offline check")
    models_p.add_argument("--url", dest="sub_url", default=None, help="Override dashboard API URL")
    models_p.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")


def _resolve_target(explicit_url: str | None, *, has_local_override: bool, offline: bool) -> tuple[str, str | None]:
    """Return ('remote', base_url) or ('local', None) from flags and environment."""
    if not offline:
        if explicit_url and explicit_url.strip():
            return "remote", explicit_url.strip().rstrip("/")
        if not has_local_override:
            env_url = (os.getenv("TRACKER_DASHBOARD_URL") or os.getenv("APP_URL") or "").strip()
            if env_url:
                return "remote", env_url.rstrip("/")
    return "local", None


def _http_json(url: str, *, method: str = "GET", timeout_s: float = 8.0) -> dict[str, Any]:
    """Execute GET or POST request and parse JSON dictionary response."""
    req = urllib.request.Request(url, data=b"" if method != "GET" else None, method=method)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _load_offline_config_into_graph(graph: WorldGraph, config_path: str) -> None:
    """Populate CameraNode, ZoneNode, and TripwireNode definitions from JSON or YAML."""
    if config_path.lower().endswith(".json"):
        with open(config_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if isinstance(raw, list):
            for idx, cam in enumerate(raw):
                cid = str(cam.get("id") or f"cam_{idx}")
                graph.register_camera(CameraNode(
                    camera_id=cid, name=str(cam.get("name") or cid),
                    source=str(cam.get("source", "")), enabled=bool(cam.get("enabled", True)),
                ))
            return
    data = load_config(config_path)
    if isinstance(data, dict) and data:
        cam_id = str(data.get("camera_id", "default"))
        cfg = PipelineConfig.from_dict(data, camera_id=cam_id, config_path=config_path)
        graph.register_camera(CameraNode(camera_id=cam_id, name=cam_id, source=str(cfg.source), enabled=True))
        register_world_children(graph, cfg, None)


def _load_offline_db_into_graph(graph: WorldGraph, db_path: str) -> None:
    """Populate WorldEntity nodes from TrackerDB entities and calibrated confidence state."""
    db = TrackerDB(db_path)
    try:
        conf_engine = ConfidenceEngine(db=db)
        for ent in db.list_entities():
            eid = int(ent["id"])
            state = conf_engine.get_state(eid)
            cam_tracks = {state.last_camera_id: 0} if (state and state.last_camera_id) else {}
            zones = {state.last_camera_id: {state.last_zone_id}} if (state and state.last_camera_id and state.last_zone_id) else {}
            graph.upsert_entity(WorldEntity(
                entity_id=eid, name=str(ent.get("name", "")), category=str(ent.get("category", "unknown")),
                confidence=float(state.confidence) if state else 0.0, camera_tracks=cam_tracks,
                active_zones=zones, last_seen=float(state.last_seen_at) if state else 0.0,
            ))
    finally:
        db.close()


def _build_offline_world_snapshot(config_path: str | None, db_path: str | None) -> dict[str, Any]:
    """Assemble an offline WorldGraph snapshot from local config and/or TrackerDB."""
    graph = WorldGraph()
    resolved_cfg = config_path or (os.path.join("configs", "cameras.json") if os.path.isfile(os.path.join("configs", "cameras.json")) else None)
    if config_path and not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    if resolved_cfg:
        _load_offline_config_into_graph(graph, resolved_cfg)

    resolved_db = db_path or (os.path.join("data", "tracker.db") if os.path.isfile(os.path.join("data", "tracker.db")) else None)
    if db_path and not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")
    if resolved_db:
        _load_offline_db_into_graph(graph, resolved_db)
    return graph.snapshot()


def _filter_entities(snap: dict[str, Any], camera_id: str | None, min_confidence: float | None) -> list[dict[str, Any]]:
    """Filter WorldGraph snapshot entities by camera_id and min_confidence."""
    entities = list((snap.get("entities") or {}).values())
    if camera_id:
        entities = [e for e in entities if camera_id in (e.get("camera_tracks") or {}) or camera_id in (e.get("active_zones") or {})]
    if min_confidence is not None:
        entities = [e for e in entities if float(e.get("confidence", 0.0)) >= float(min_confidence)]
    entities.sort(key=lambda e: (-float(e.get("last_seen", 0.0)), str(e.get("world_entity_id", ""))))
    return entities


def _print_world_output(action: str, payload: dict[str, Any], as_json: bool) -> None:
    """Render WorldGraph summary, entities, or snapshot."""
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return
    if action == "entities":
        entities = payload.get("entities") or []
        print(f"World Entities ({len(entities)}):")
        for ent in entities:
            cams = ",".join(sorted((ent.get("camera_tracks") or {}).keys())) or "-"
            print(f"  - {ent.get('name') or ent.get('world_entity_id')} [{ent.get('category')}] conf={float(ent.get('confidence', 0.0)):.2f} cams={cams}")
        return
    counts = payload.get("counts") or {}
    print(
        "WorldGraph Summary:\n"
        f"  Cameras   : {counts.get('cameras', 0)}\n"
        f"  Zones     : {counts.get('zones', 0)}\n"
        f"  Tripwires : {counts.get('tripwires', 0)}\n"
        f"  Entities  : {counts.get('entities', 0)}"
    )


def execute_world_args(args: argparse.Namespace, *, fallback_url: str | None = None) -> int:
    """Execute the `world` subcommand and return an exit code."""
    explicit_url = getattr(args, "sub_url", None) or fallback_url
    has_local = bool(getattr(args, "config", None) or getattr(args, "db", None))
    mode, base_url = _resolve_target(explicit_url, has_local_override=has_local, offline=bool(args.offline))
    try:
        if mode == "remote" and base_url:
            if args.action == "entities":
                qs = urllib.parse.urlencode(
                    {k: v for k, v in {"camera_id": args.camera_id, "min_confidence": args.min_confidence}.items() if v is not None}
                )
                suffix = f"/api/world/entities?{qs}" if qs else "/api/world/entities"
                payload = _http_json(f"{base_url}{suffix}")
            else:
                payload = _http_json(f"{base_url}/api/world/snapshot")
        else:
            snap = _build_offline_world_snapshot(getattr(args, "config", None), getattr(args, "db", None))
            if args.action == "entities":
                filtered = _filter_entities(snap, args.camera_id, args.min_confidence)
                payload = {"count": len(filtered), "entities": filtered}
            else:
                payload = snap
    except (FileNotFoundError, urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        print(f"[ERROR] World inspection failed ({mode}): {exc}", file=sys.stderr)
        return 1
    _print_world_output(args.action, payload, bool(args.as_json))
    return 0


def execute_models_args(args: argparse.Namespace, *, fallback_url: str | None = None) -> int:
    """Execute the `models` subcommand and return an exit code."""
    download_target = getattr(args, "download", None)
    if download_target is not None or args.action == "download":
        target = download_target or "all"
        try:
            result = download_model(target, output_dir=args.models_dir, force=bool(args.force))
            out = {"downloaded": target, "result": result}
            print(json.dumps(out, indent=2) if args.as_json else f"[OK] Downloaded {target}: {result}")
            return 0
        except Exception as exc:
            print(f"[ERROR] Model download failed: {exc}", file=sys.stderr)
            return 1

    explicit_url = getattr(args, "sub_url", None) or fallback_url
    do_verify = bool(args.verify or args.action == "verify")
    mode, base_url = _resolve_target(explicit_url, has_local_override=bool(args.models_dir), offline=bool(args.offline))
    try:
        if mode == "remote" and base_url:
            endpoint = "/api/system/models/verify" if do_verify else "/api/system/models"
            payload = _http_json(f"{base_url}{endpoint}", method="POST" if do_verify else "GET")
        else:
            payload = check_status(output_dir=args.models_dir, verify=True, quiet=bool(args.as_json))
            if not args.as_json:
                return 0
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        print(f"[ERROR] Model status check failed ({mode}): {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"Models ({payload.get('models_dir', '')}):")
        for m in payload.get("models", []):
            print(f"  - {m.get('name'):<12}: {str(m.get('status', '')).upper()} ({m.get('filename')})")
    return 0
