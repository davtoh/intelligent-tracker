"""Computational geometry package: polygon clipping, primitives, tripwires, and zones.

Re-exports 100% of public primitives, polygon math, and retail analytics geometry
to preserve complete backward compatibility across all modules and tests.
"""

from intelligent_tracker.geometry.associations import Completeness
from intelligent_tracker.geometry.intersections import (
    EspList,
    cnt_check_intersection,
    cnt_intersection,
    intersect_analytical,
    mixed_intersections,
)
from intelligent_tracker.geometry.polygons import (
    BasePoly,
    Interception,
    PolyLine,
)
from intelligent_tracker.geometry.primitives import (
    IncompleteAssociations,
    NotInvertible,
    bezier,
    cnt_group,
    go_around,
    line_intersection,
    norm_point,
    segments_intersect,
)
from intelligent_tracker.geometry.raster import (
    draw_drawContours,
    draw_fillConvexPoly,
    draw_fillPoly,
    intersect_ADD,
    intersect_AND,
)
from intelligent_tracker.geometry.tripwire import (
    Tripwire,
    TripwireEvent,
)
from intelligent_tracker.geometry.zone_roi import (
    ZoneEvent,
    ZoneROI,
)

__author__ = "David Toro"
__license__ = "GPL"
__maintainer__ = "David Toro"
__email__ = "davsamirtor@gmail.com"

__all__ = [
    # Primitives & Exceptions
    "NotInvertible",
    "IncompleteAssociations",
    "norm_point",
    "bezier",
    "line_intersection",
    "cnt_group",
    "go_around",
    "segments_intersect",
    # Polygons & Chains
    "BasePoly",
    "Interception",
    "PolyLine",
    # Associations & Graph
    "Completeness",
    # Intersections & Solvers
    "EspList",
    "cnt_check_intersection",
    "cnt_intersection",
    "intersect_analytical",
    "mixed_intersections",
    # Raster Drawing & Boolean Ops
    "draw_drawContours",
    "draw_fillConvexPoly",
    "draw_fillPoly",
    "intersect_AND",
    "intersect_ADD",
    # Zones & Tripwires
    "Tripwire",
    "TripwireEvent",
    "ZoneEvent",
    "ZoneROI",
]
