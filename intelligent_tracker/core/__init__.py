"""Core Scene Graph and Spatial Hierarchy Package.

Re-exports 100% of public spatial graph, group, agent, and trajectory primitives
to preserve complete backward compatibility across all modules and tests.
"""

import sys
from weakref import ref
import cv2

from intelligent_tracker.core.agents import Agent
from intelligent_tracker.core.complete_groups import CompleteGroup
from intelligent_tracker.core.groups import Group, GroupHandle
from intelligent_tracker.core.spaces import MetaSpace, Space, deco_name
from intelligent_tracker.core.tails import Point, TailItem
from intelligent_tracker.core.weakref_utils import (
    SpaceHandle,
    WeakRefDictionary,
    WeakWatcher,
    WeakWatcherDictionary,
    WeakWatcherWithData,
)

_cv_ver = cv2.__version__.split('.')
cv_major_ver = _cv_ver[0]
cv_minor_ver = _cv_ver[1] if len(_cv_ver) > 1 else '0'
cv_subminor_ver = _cv_ver[2] if len(_cv_ver) > 2 else '0'
PY3 = sys.version_info[0] == 3
if PY3:
    xrange = range

__author__ = "David Toro"
__license__ = "GPL"
__maintainer__ = "David Toro"
__email__ = "davsamirtor@gmail.com"

__all__ = [
    # Weak reference and Space handle helpers
    "SpaceHandle",
    "WeakWatcher",
    "WeakWatcherWithData",
    "WeakWatcherDictionary",
    "WeakRefDictionary",
    "ref",
    # Spaces & Metaclasses
    "MetaSpace",
    "Space",
    "deco_name",
    # Groups & Collections
    "GroupHandle",
    "Group",
    "CompleteGroup",
    # Agents & Representations
    "Agent",
    # Trajectory & Geometry
    "Point",
    "TailItem",
    # OpenCV & Python compatibility helpers
    "cv_major_ver",
    "cv_minor_ver",
    "cv_subminor_ver",
    "xrange",
    "PY3",
]

