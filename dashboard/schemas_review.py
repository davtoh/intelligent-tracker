"""Pydantic Schemas for Reversible Active Learning Review Decisions & Undo."""

from typing import Any

from pydantic import BaseModel, Field


class ReviewUndoRequest(BaseModel):
    """Optional request body for undoing a review decision."""

    reviewer: str = Field("operator", description="Operator performing the undo")
    notes: str = Field("", description="Optional reason for reverting the decision")


class ReviewDecisionRecord(BaseModel):
    """Serialized audit row from ``review_decisions``."""

    id: int
    review_id: int
    action: str
    prior_status: str = "pending"
    prior_entity_id: int | None = None
    new_entity_id: int | None = None
    created_signature_id: int | None = None
    created_descriptor_version_id: int | None = None
    created_sighting_id: int | None = None
    created_negative_exemplar_id: int | None = None
    created_entity_id: int | None = None
    prior_state: dict[str, Any] = Field(default_factory=dict)
    reviewer: str = "operator"
    notes: str = ""
    undone: bool = False
    undone_at: str | None = None
    undone_by: str = ""
    created_at: str | None = None


class ReviewUndoResponse(BaseModel):
    """Response payload returned after undoing a review decision."""

    status: str
    decision_id: int | None = None
    review_id: int | None = None
    action: str = ""
    reverted: dict[str, Any] = Field(default_factory=dict)
    relabelled_runs: int = 0


class ReportWrongSightingRequest(BaseModel):
    """Request payload for flagging a false-positive sighting from #timeline."""

    sighting_id: int | None = None
    entity_id: int | None = None
    camera_id: str = ""
    video_filename: str = ""
    media_offset_sec: float = 0.0
    track_id: int = 0
    run_id: str = ""
    crop_path: str = ""
    bbox: list[int] | None = None
    notes: str = ""
    reviewer: str = "operator"


class TagCorrectRequest(BaseModel):
    """Request payload for correcting a Known-state entity match in #modal-tag-entity."""

    prior_entity_id: int
    entity_name: str = Field(..., min_length=1)
    category: str = Field("person")
    entity_id: int | None = None
    camera_id: str | None = None
    video_filename: str | None = None
    timestamp_sec: float | None = None
    bbox: list[int] | None = None
    crop_base64: str | None = None
    notes: str = Field("")
    track_id: int | None = None
    run_id: str = Field("")
    reviewer: str = Field("operator")


class BulkDismissRequest(BaseModel):
    """Request payload for bulk-dismissing pending review queue candidates."""

    item_ids: list[int] | None = Field(default=None, description="Optional explicit list of review item IDs")
    status: str = Field(default="pending", description="Target status filter (defaults to pending)")
    matched: str | None = Field(default=None, description="Optional match filter: 'matched' or 'unmatched'")
    reason: str | None = Field(default=None, description="Optional reason filter: 'borderline' or 'reported_wrong'")
    reviewer: str = Field(default="operator", description="Operator performing the bulk dismissal")
