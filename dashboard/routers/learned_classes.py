"""FastAPI router for exemplar learned classes and per-camera COCO overrides."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from dashboard.dependencies import CROPS_DIR, get_camera_pool, get_db
from dashboard.services.learned_class_service import LearnedClassService

router = APIRouter(tags=["learned-classes"])


class LearnedClassCreateRequest(BaseModel):
    """Payload for creating a new exemplar learned class."""

    name: str = Field(..., min_length=1, max_length=80)
    slug: str = Field(default="", max_length=80)
    parent_coco_class: str = Field(default="", max_length=64)
    color: str = Field(default="#06B6D4", max_length=32)
    threshold: float = Field(default=0.65, ge=0.1, le=0.99)
    description: str = Field(default="", max_length=300)


class LearnedClassUpdateRequest(BaseModel):
    """Payload for updating an existing learned class."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    slug: str | None = Field(default=None, max_length=80)
    parent_coco_class: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=32)
    threshold: float | None = Field(default=None, ge=0.1, le=0.99)
    description: str | None = Field(default=None, max_length=300)


class ExemplarEnrollRequest(BaseModel):
    """Payload for enrolling a visual exemplar crop into a learned class."""

    crop_base64: str = Field(default="")
    camera_id: str = Field(default="", max_length=64)
    bbox: list[float] | None = Field(default=None)
    notes: str = Field(default="", max_length=300)
    force: bool = Field(default=False)


class CameraClassOverrideRequest(BaseModel):
    """Payload for setting a per-camera COCO class suppress/relabel override."""

    coco_class: str = Field(..., min_length=1, max_length=64)
    action: str = Field(default="suppress", pattern="^(suppress|relabel)$")
    relabel_to: str = Field(default="", max_length=80)


def _service(request: Request) -> LearnedClassService:
    """Build a LearnedClassService bound to the current app DB and CameraPool."""
    db = get_db(request)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return LearnedClassService(db=db, camera_pool=get_camera_pool(request), crops_dir=CROPS_DIR)


@router.get("/api/classes/learned")
async def list_learned_classes(request: Request) -> list[dict[str, Any]]:
    """List all exemplar learned classes."""
    return await asyncio.to_thread(_service(request).list_classes)


@router.post("/api/classes/learned", status_code=201)
async def create_learned_class(payload: LearnedClassCreateRequest, request: Request) -> dict[str, Any]:
    """Create a new exemplar learned class."""
    try:
        return await asyncio.to_thread(_service(request).create_class, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="Learned class name or slug already exists") from exc
        raise HTTPException(status_code=500, detail="Failed to create learned class") from exc


@router.put("/api/classes/learned/{class_id}")
async def update_learned_class(class_id: int, payload: LearnedClassUpdateRequest, request: Request) -> dict[str, Any]:
    """Update an existing learned class."""
    updated = await asyncio.to_thread(
        _service(request).update_class, class_id, payload.model_dump(exclude_none=True),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Learned class not found")
    return updated


@router.delete("/api/classes/learned/{class_id}")
async def delete_learned_class(class_id: int, request: Request) -> dict[str, Any]:
    """Delete a learned class and its exemplars."""
    deleted = await asyncio.to_thread(_service(request).delete_class, class_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Learned class not found")
    return {"status": "deleted", "class_id": class_id}


@router.post("/api/classes/learned/{class_id}/exemplars")
async def enroll_learned_exemplar(class_id: int, payload: ExemplarEnrollRequest, request: Request) -> dict[str, Any]:
    """Enroll a visual exemplar crop into a learned class with collision checking."""
    try:
        return await asyncio.to_thread(
            _service(request).enroll_exemplar,
            class_id,
            crop_base64=payload.crop_base64,
            camera_id=payload.camera_id,
            bbox=payload.bbox,
            notes=payload.notes,
            force=payload.force,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/api/classes/learned/exemplars/{exemplar_id}")
async def delete_learned_exemplar(exemplar_id: int, request: Request) -> dict[str, Any]:
    """Delete a single learned class exemplar."""
    deleted = await asyncio.to_thread(_service(request).delete_exemplar, exemplar_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Exemplar not found")
    return {"status": "deleted", "exemplar_id": exemplar_id}


@router.get("/api/classes/overrides/{camera_id}")
async def get_camera_overrides(camera_id: str, request: Request) -> list[dict[str, Any]]:
    """List per-camera COCO class suppress/relabel overrides."""
    return await asyncio.to_thread(_service(request).get_camera_overrides, camera_id)


@router.put("/api/classes/overrides/{camera_id}")
async def set_camera_override(camera_id: str, payload: CameraClassOverrideRequest, request: Request) -> dict[str, Any]:
    """Upsert a per-camera COCO class suppress/relabel override."""
    try:
        return await asyncio.to_thread(
            _service(request).set_camera_override,
            camera_id,
            payload.coco_class,
            payload.action,
            payload.relabel_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/classes/overrides/{camera_id}/{coco_class}")
async def delete_camera_override(camera_id: str, coco_class: str, request: Request) -> dict[str, Any]:
    """Remove a per-camera COCO class override."""
    deleted = await asyncio.to_thread(_service(request).delete_camera_override, camera_id, coco_class)
    if not deleted:
        raise HTTPException(status_code=404, detail="Override not found")
    return {"status": "deleted", "camera_id": camera_id, "coco_class": coco_class}
