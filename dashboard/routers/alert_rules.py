"""REST API Router for Alert Promotion Rules & Global Alert Policy Settings."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from dashboard.dependencies import get_camera_pool, get_db
from intelligent_tracker.database import TrackerDB

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class AlertRuleCreateRequest(BaseModel):
    """Payload for creating an alert promotion rule."""

    name: str = Field(..., min_length=1, max_length=120)
    enabled: bool = True
    event_type: str = ""
    zone_id: str = ""
    camera_id: str = ""
    category: str = ""
    min_dwell_time: float | None = Field(default=None, ge=0.0)
    target_severity: str = "warning"
    add_tags: str = ""


class AlertRuleUpdateRequest(BaseModel):
    """Payload for updating an existing alert promotion rule."""

    name: str | None = None
    enabled: bool | None = None
    event_type: str | None = None
    zone_id: str | None = None
    camera_id: str | None = None
    category: str | None = None
    min_dwell_time: float | None = Field(default=None, ge=0.0)
    target_severity: str | None = None
    add_tags: str | None = None


class AlertPolicyUpdateRequest(BaseModel):
    """Payload for updating global alert policy settings."""

    dwell_override: float | None = Field(default=None, ge=0.0)
    alert_sensitivity: float | None = Field(default=None, ge=0.0, le=10.0)
    quiet_hours: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None


def _reload_promotion_engine(request: Request) -> None:
    """Reload live AlertPromotionEngine rules after DB mutations."""
    pool = get_camera_pool(conn=request)
    engine = getattr(pool, "promotion_engine", None) if pool is not None else None
    if engine is None:
        fts = getattr(pool, "event_fts_index", None) or getattr(request.app.state, "event_fts_index", None)
        engine = getattr(fts, "promotion_engine", None) if fts is not None else None
    if engine is not None and hasattr(engine, "reload"):
        engine.reload()


def _sync_world_policy(request: Request, policy: dict[str, Any]) -> None:
    """Push updated alert policy to AlertPromotionEngine and WorldGraph."""
    pool = get_camera_pool(conn=request)
    engine = getattr(pool, "promotion_engine", None) if pool is not None else None
    if engine is not None and hasattr(engine, "sync_policy"):
        engine.sync_policy(policy)
        return
    wg = getattr(pool, "world_graph", None) or getattr(request.app.state, "world_graph", None)
    updater = getattr(wg, "update_policy", None) or getattr(wg, "set_policy", None) if wg is not None else None
    if callable(updater):
        updates = {k: policy[k] for k in ("dwell_override", "alert_sensitivity", "quiet_hours", "extra") if k in policy}
        if updates:
            updater(**updates)


@router.get("/rules")
async def list_alert_rules(enabled_only: bool = False, db: TrackerDB = Depends(get_db)):
    """List persisted alert promotion rules."""
    rules = await asyncio.to_thread(db.list_alert_rules, enabled_only=enabled_only)
    return {"rules": rules}


@router.post("/rules", status_code=201)
async def create_alert_rule(req: AlertRuleCreateRequest, request: Request, db: TrackerDB = Depends(get_db)):
    """Create a new alert promotion rule and reload the live engine."""
    try:
        rule = await asyncio.to_thread(db.create_alert_rule, **req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await asyncio.to_thread(_reload_promotion_engine, request)
    return {"rule": rule}


@router.put("/rules/{rule_id}")
async def update_alert_rule(
    rule_id: int, req: AlertRuleUpdateRequest, request: Request, db: TrackerDB = Depends(get_db)
):
    """Update an existing alert promotion rule and reload the live engine."""
    payload = req.model_dump(exclude_unset=True)
    try:
        rule = await asyncio.to_thread(db.update_alert_rule, rule_id, **payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Alert rule {rule_id} not found")
    await asyncio.to_thread(_reload_promotion_engine, request)
    return {"rule": rule}


@router.delete("/rules/{rule_id}")
async def delete_alert_rule(rule_id: int, request: Request, db: TrackerDB = Depends(get_db)):
    """Delete an alert promotion rule and reload the live engine."""
    deleted = await asyncio.to_thread(db.delete_alert_rule, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Alert rule {rule_id} not found")
    await asyncio.to_thread(_reload_promotion_engine, request)
    return {"deleted": True, "rule_id": rule_id}


@router.get("/policy")
async def get_alert_policy(db: TrackerDB = Depends(get_db)):
    """Return global alert policy settings."""
    policy = await asyncio.to_thread(db.get_alert_policy)
    return {"policy": policy}


@router.put("/policy")
async def update_alert_policy(req: AlertPolicyUpdateRequest, request: Request, db: TrackerDB = Depends(get_db)):
    """Update global alert policy settings and sync WorldGraph.update_policy()."""
    payload = req.model_dump(exclude_unset=True)
    policy = await asyncio.to_thread(db.update_alert_policy, **payload)
    await asyncio.to_thread(_sync_world_policy, request, policy)
    return {"policy": policy}
