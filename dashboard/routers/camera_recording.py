"""Dashboard API Router for live camera stream MP4 recording."""

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from dashboard.camera_pool import CameraPool
from dashboard.dependencies import VIDEOS_DIR, get_camera_pool, get_stream_manager
from dashboard.schemas import CameraRecordStartRequest, CameraRecordStatusResponse
from dashboard.stream_manager import StreamManager

router = APIRouter(tags=["Camera Recording"])


def _resolve_camera_stream(
    camera_id: str,
    pool: Optional[CameraPool],
    sm: Optional[StreamManager],
) -> StreamManager:
    """Resolve active StreamManager from CameraPool or primary StreamManager fallback."""
    mgr = None
    if pool is not None:
        if camera_id in pool.camera_configs or camera_id in pool.streams:
            mgr = pool.get_stream(camera_id)
    if mgr is None and sm is not None and sm.camera_id == camera_id:
        mgr = sm
    if mgr is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return mgr


@router.post("/api/cameras/{camera_id}/record/start", response_model=CameraRecordStatusResponse)
async def start_camera_recording(
    camera_id: str,
    req: Optional[CameraRecordStartRequest] = Body(default=None),
    pool: Optional[CameraPool] = Depends(get_camera_pool),
    sm: Optional[StreamManager] = Depends(get_stream_manager),
):
    """Start live MP4 recording for a camera stream."""
    mgr = _resolve_camera_stream(camera_id, pool, sm)
    params = req or CameraRecordStartRequest()
    try:
        return mgr.start_recording(
            filename=params.filename,
            fps=params.fps,
            annotated=params.annotated,
            max_frames=params.max_frames,
            max_duration_s=params.max_duration_s,
            output_dir=VIDEOS_DIR,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/cameras/{camera_id}/record/stop", response_model=CameraRecordStatusResponse)
async def stop_camera_recording(
    camera_id: str,
    pool: Optional[CameraPool] = Depends(get_camera_pool),
    sm: Optional[StreamManager] = Depends(get_stream_manager),
):
    """Stop active MP4 recording for a camera stream."""
    mgr = _resolve_camera_stream(camera_id, pool, sm)
    try:
        return mgr.stop_recording()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/cameras/{camera_id}/record/status", response_model=CameraRecordStatusResponse)
async def get_camera_recording_status(
    camera_id: str,
    pool: Optional[CameraPool] = Depends(get_camera_pool),
    sm: Optional[StreamManager] = Depends(get_stream_manager),
):
    """Retrieve current or last finalized MP4 recording status for a camera stream."""
    mgr = _resolve_camera_stream(camera_id, pool, sm)
    return mgr.get_recording_status()
