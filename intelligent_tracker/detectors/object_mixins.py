"""Mixins decomposing spatial queries, kinematics, and visual rendering for Object."""

from collections import deque
import cv2
import numpy as np
from intelligent_tracker.array_utils import norm_range
from intelligent_tracker.core import cv_major_ver, xrange


def _create_cv2_tracker(tracker_type: str):
    """Instantiate a cv2 or cv2.legacy tracking algorithm by name."""
    tk_name = tracker_type.upper()

    def _get_cv2_tracker_fn(method_name: str):
        if hasattr(cv2, method_name):
            return getattr(cv2, method_name)()
        if hasattr(cv2, "legacy") and hasattr(cv2.legacy, method_name):
            return getattr(cv2.legacy, method_name)()
        raise ValueError(
            f"Tracker '{method_name}' is not available in OpenCV {getattr(cv2, '__version__', 'unknown')}"
        )

    if int(cv_major_ver) < 3:
        return cv2.Tracker_create(tk_name)

    mapping = {
        "BOOSTING": "TrackerBoosting_create",
        "MIL": "TrackerMIL_create",
        "KCF": "TrackerKCF_create",
        "TLD": "TrackerTLD_create",
        "MEDIANFLOW": "TrackerMedianFlow_create",
        "MOSSE": "TrackerMOSSE_create",
        "CSRT": "TrackerCSRT_create",
        "GOTURN": "TrackerGOTURN_create",
    }
    if tk_name in mapping:
        return _get_cv2_tracker_fn(mapping[tk_name])
    raise ValueError(f"tracker_type '{tracker_type}' not supported")


class ObjectGeometryMixin:
    """Properties for contour, rotated bounding box, and zone containment."""

    @property
    def cnt(self):
        return self.tail[0].cnt

    @cnt.setter
    def cnt(self, value):
        return

    @property
    def rotated_box(self):
        return self.tail[0].rbox

    @rotated_box.setter
    def rotated_box(self, value):
        return

    @property
    def in_zones(self):
        return self._in_zones

    @in_zones.setter
    def in_zones(self, zones):
        to_eliminate = []
        _in_zones = self._in_zones
        for oz in _in_zones:
            if oz in zones:
                zones.remove(oz)
            else:
                to_eliminate.append(oz)
        for i in to_eliminate:
            _in_zones.remove(i)
            i._space_remove_child(self)
        for nz in zones:
            _in_zones.append(nz)
            nz._space_add_child(self)

    @in_zones.deleter
    def in_zones(self):
        self.in_zones = []


class ObjectDynamicsMixin:
    """Properties for movement velocity deltas, tail lengths, and tracking state."""

    @property
    def dX(self):
        """Get X position delta."""
        self.compute()
        return self._dX

    @property
    def dY(self):
        """Get Y position delta."""
        self.compute()
        return self._dY

    @property
    def dZ(self):
        """Get Z position delta."""
        self.compute()
        return self._dZ

    @property
    def tail_len(self):
        return len(self.tail)

    @property
    def max_tail_len(self):
        return self.tail.maxlen

    @max_tail_len.setter
    def max_tail_len(self, new_len: int):
        if not self._enough_items(new_len):
            raise ValueError(
                f"max_tail_len must be greater than {self._enough_items()} and got '{new_len}'"
            )

        try:
            old_len = self.tail.maxlen
        except AttributeError:
            old_len = new_len + 1

        if old_len != new_len:
            c_len = min([old_len, new_len])
            cached_tail = self.tail
            self.tail = deque(maxlen=new_len)
            if cached_tail:
                for i, p in enumerate(cached_tail):
                    if i > c_len:
                        break
                    self.tail.append(p)

    @property
    def is_tracking(self):
        return self._is_tracking

    @is_tracking.setter
    def is_tracking(self, value: bool):
        if value and not self._is_tracking:
            last = self.tail[0]
            self.tail.clear()
            self.tail.append(last)
        self._is_tracking = value


class ObjectSpatialMixin:
    """Spatial queries and geometric intersection tests for Object."""

    def _update_description(self, frame, tail_item):
        return

    def _fill_mask(self, mask, tail_item):
        cv2.drawContours(mask, [tail_item.cnt], -1, 1, -1)

    def point_inside(self, point):
        """Test whether point is inside object in last position.

        :param point: point or x-coordinate, y-coordinate
        :return: True if inside or in contour, else False
        """
        return self.tail[0].point_inside(point)

    def point_near(self, point):
        """Test whether point is near object in last position.

        :param point: point or x-coordinate, y-coordinate
        :return: True if inside or in contour, else False
        """
        return self.tail[0].point_near(point)

    def cnt_intersect(self, cnt):
        """Test whether last internal cnt from tail is intersected with external cnt.

        :param cnt: external contour
        :return: True if contours intersect, else False
        """
        return self.tail[0].cnt_intersect(cnt)

    def cnt_near(self, cnt):
        """Test whether last internal cnt from tail is near with external cnt.

        :param cnt: external contour
        :return: True if contours intersect, else False
        """
        return self.tail[0].cnt_near(cnt)


class ObjectKinematicsMixin:
    """Kinematics, trajectory computation, and OpenCV tracker updates."""

    def direction(
        self,
        x_axis=("left", "right"),
        y_axis=("up", "down"),
        z_axis=("far", "near"),
    ):
        """Get tracked object direction in a readable string format.

        :param x_axis: names of extremes in x axis. ("left", "right")
        :param y_axis: names of extremes in y axis. ("up", "down")
        :param z_axis: names of extremes in z axis. ("far", "near")
        :return: x_axis, y_axis, z_axis directions joined by '-'
        """
        dirX, dirY, dirZ = "", "", ""
        if not self.compute():
            return "-".join((dirX, dirY, dirZ))

        dX, dY, dZ = self._dX, self._dY, self._dZ
        if np.abs(dX) > 0:
            dirX = x_axis[1] if np.sign(dX) == 1 else x_axis[0]
        if np.abs(dY) > 0:
            dirY = y_axis[1] if np.sign(dY) == 1 else y_axis[0]
        if np.abs(dZ) > 0:
            dirZ = z_axis[1] if np.sign(dY) == 1 else z_axis[0]

        return "-".join((dirX, dirY, dirZ))

    def _compute(self):
        tail = self.tail
        if not self._enough_items(len(tail)):
            return

        cover = self._direction_cover
        average = (
            np.sum(
                np.array([np.array(tail[i].pt) * (cover - i) for i in xrange(cover)]),
                0,
            )
            / np.sum(np.arange(cover) + 1)
        )
        rolled = (
            np.sum(
                np.array([np.array(tail[-i - 1].pt) * (cover - i) for i in xrange(cover)]),
                0,
            )
            / np.sum(np.arange(cover) + 1)
        )
        self._dX, self._dY, self._dZ = [int(i) for i in (average - rolled)]
        self._to_recompute = False

    def update_tracker(self, frame, mask=None, tracker_type=None, **kwargs):
        """Initialize or renew tracking mechanism on current frame."""
        if tracker_type is None:
            tracker_type = self.tracker_type

        tracker = _create_cv2_tracker(tracker_type)

        if kwargs:
            tf = self.add_to_tail(mask=mask, frame=frame, **kwargs)
        else:
            tf = self.tail[0]

        self.tracker_type = tracker_type
        self.tracker = tracker
        self.is_tracking = tracker.init(frame, tf.bbox)

    def update(self, frame, mask=None):
        """Update tracker bounding box with new frame and record to tail."""
        self.is_tracking, bbox = self.tracker.update(frame)
        if self.is_tracking:
            self.add_to_tail(mask=mask, frame=frame, bbox=bbox)


class ObjectVisualMixin:
    """Visual rendering, tail drawing, and statistical overlays for Object."""

    def get_BGR_color(self):
        """Get object color assigned from parent Detector or randomly generated."""
        if self._BGR_color is None:
            try:
                self._BGR_color = norm_range(self._space_parent.get_BGR_color())
            except AttributeError:
                self._BGR_color = norm_range(np.random.rand(3) * 255)
        return self._BGR_color

    def draw_circle(self, frame, color=None):
        """Draw circular centroid and bounding radius on frame."""
        color = self.get_BGR_color() if color is None else norm_range(color)
        try:
            x, y, _ = self.position
            _, radius = cv2.minEnclosingCircle(self.tail[0].cnt)
            center = (int(x), int(y))
            cv2.circle(frame, center, int(radius), color, 2)
            cv2.circle(frame, center, 5, norm_range([255 - i for i in color]), -1)
        except IndexError:
            pass

    def draw_tail(self, frame, color=None, iterate=None):
        """Draw historical trajectory line segments on frame with fading thickness."""
        color = self.get_BGR_color() if color is None else norm_range(color)
        tail = self.tail
        if iterate is None:
            iterate = xrange(1, len(tail))
        for i in iterate:
            if tail[i - 1] is None or tail[i] is None:
                continue
            thickness = int(np.sqrt(self.tail_len / float(i + 1)) * 2.5)
            cv2.line(frame, tail[i - 1].pt[:2], tail[i].pt[:2], color, thickness)

    def draw_stats(
        self,
        frame,
        position=None,
        fontFace=None,
        fontScale=None,
        color=None,
        thickness=None,
        tag=None,
    ):
        """Render movement velocity deltas and direction on frame."""
        if position is None:
            position = (10, frame.shape[0] - 10)
        if fontFace is None:
            fontFace = cv2.FONT_HERSHEY_SIMPLEX
        if fontScale is None:
            fontScale = 0.35
        color = self.get_BGR_color() if color is None else norm_range(color)
        if thickness is None:
            thickness = 1
        if tag is None:
            tag = "dx: {dx}, dy: {dy}, dz: {dz} \n{direction}"

        text = tag.format(
            dx=self.dX, dy=self.dY, dz=self.dZ, direction=self.direction()
        )
        cv2.putText(
            frame,
            text,
            position,
            fontFace=fontFace,
            fontScale=fontScale,
            color=color,
            thickness=thickness,
        )

    def __json_enco__(self):
        return self.max_tail_len

    def _parent_changed_event(self, old_parent):
        return
