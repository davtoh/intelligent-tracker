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
