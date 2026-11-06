"""Object entity representation, bounding boxes, and track lifecycle."""

from typing import Any, Optional

from intelligent_tracker.core import Agent, TailItem
from intelligent_tracker.detectors.object_mixins import (
    ObjectDynamicsMixin,
    ObjectGeometryMixin,
    ObjectKinematicsMixin,
    ObjectSpatialMixin,
    ObjectVisualMixin,
)


class Object(
    ObjectGeometryMixin,
    ObjectDynamicsMixin,
    ObjectSpatialMixin,
    ObjectKinematicsMixin,
    ObjectVisualMixin,
    Agent,
):
    """It is any entity in the World that has its own characteristics or

    features and that can be tracked in the real world.
    """

    def __init__(
        self,
        frame,
        parent_detector,
        max_tail_len: int = 30,
        tracker_type: str = "MEDIANFLOW",
        key_pts: Optional[Any] = None,
        descriptors: Optional[Any] = None,
        **kwargs,
    ):
        super().__init__()
        self._space_parent = parent_detector
        self._dX, self._dY, self._dZ = None, None, None
        self._BGR_color = None
        self._to_recompute = True
        self.key_pts = key_pts
        self.descriptors = descriptors
        self._direction_cover = 10
        self.tail = None
        self.max_tail_len = max_tail_len
        self.tracker_type = tracker_type
        self.tracker = None
        self._is_tracking = False
        self._stray_count = 0
        self._max_stray_count = 10
        self.live_forever = False
        self._in_zones = []

        self.add_to_tail(**kwargs)
        self.update_tracker(frame)

    def _enough_items(self, no_items: Optional[int] = None):
        """Test whether number of tail items are enough to calculate direction.

        :param no_items: number of items in tail
        :return: True if no_items can be processed, or required threshold if no_items is None.
        """
        to_cover = self._direction_cover * 2
        if no_items is None:
            return to_cover
        if no_items >= to_cover:
            return True

    @property
    def position(self):
        """Return last tracked point or position centroid."""
        return self.tail[0].pt

    def add_to_tail(self, *args, **kwargs):
        """Add a tail_item itself or from a contour (cnt), bounding box (bbox)

        or rotated box (rbox) to the tail. The point (pt) can be specified
        on creation but not if tail_item is given

        :param args: {0}
        :param kwargs: {0}
        :return: tail_item
        """
        frame = kwargs.pop("frame", None)
        mask = kwargs.pop("mask", None)
        try:
            tf = kwargs["tail_item"]
        except KeyError:
            tf = TailItem(*args, **kwargs)
        self.tail.appendleft(tf)
        self._to_recompute = True
        if frame is not None:
            self._update_description(frame, tf)
        if mask is not None:
            self._fill_mask(mask, tf)
        return tf

    add_to_tail.__doc__ = add_to_tail.__doc__.format(TailItem._fields)
