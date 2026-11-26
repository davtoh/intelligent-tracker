"""Helper for post-enrollment relabeling and gallery reload side effects."""

from typing import Any

from dashboard.dependencies import get_camera_pool, get_db, reload_all_galleries
from dashboard.services.video_run_relabel_service import relabel_video_runs_on_entity_mutation


def finalize_enrollment_side_effects(request: Any, res: Any) -> None:
    """Relabel matching video runs and reload all pool galleries after enrollment."""
    ent_id = res.get("entity_id") if isinstance(res, dict) else None
    if ent_id is not None:
        relabel_video_runs_on_entity_mutation(
            get_db(conn=request),
            pool=get_camera_pool(conn=request),
            updated_entity_id=int(ent_id),
        )
    reload_all_galleries(conn=request)
