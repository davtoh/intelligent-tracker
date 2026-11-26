"""Router exposing Re-ID gallery dimension health diagnostics."""

from fastapi import APIRouter, Depends

from dashboard.dependencies import get_db
from dashboard.services.gallery_health_service import inspect_gallery_health

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/gallery-health")
def get_gallery_health(db=Depends(get_db)):
    """Return canonical DualModel gallery dimension health and mismatch counts."""
    return inspect_gallery_health(db)
