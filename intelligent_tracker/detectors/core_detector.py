"""Core Detector base class, lifecycle queries, and frame processing pipelines."""

from typing import Optional
import cv2
import numpy as np

from intelligent_tracker.array_utils import draw_contour_groups, is_numpy, norm_range
from intelligent_tracker.core import Group, Space, TailItem
from intelligent_tracker.detectors.base import BaseDetector, Detection, DetectorFactory
from intelligent_tracker.detectors.objects import Object


class DetectorObjectLifecycleMixin:
    """Object lifecycle filtering and state tracking queries."""

    def active_objects(self):
        """Yield objects that are active regardless of tracking state."""
        for o in self.objects:
            if o.active:
                yield o

    def inactive_objects(self):
        """Yield objects that are inactive."""
        for o in self.objects:
            if not o.active:
                yield o

    def tracked_objects(self):
        """Yield active objects currently being tracked."""
        for o in self.objects:
            if o.active and o.is_tracking:
                yield o

    def untracked_objects(self):
        """Yield active objects not currently tracked."""
        for o in self.objects:
            if not o.active or not o.is_tracking:
                yield o

    def track_objects(self, frame, mask=None):
        """Update active object trackers without creating new objects."""
        for o in self.objects:
            if o.active:
                o.update(frame, mask)

    def delete_stray_objects(self):
        """Delete all objects that have exceeded max stray counts."""
        for o in self.objects:
            if o.active and not o.live_forever and o._stray_count > o._max_stray_count:
                o._space_delete()


class DetectorProcessingMixin:
    """Frame detection processing, tail item classification, and candidate filtering."""

    def detect_raw_objects(self, frame, mask=None):
        """Bridge modern detect() outputs to legacy TailItem objects."""
        detect_func = type(self).detect
        if detect_func is not Detector.detect:
            detections = self.detect(frame)
            if detections:
                return [TailItem(bbox=d.bbox) for d in detections]
        return None

    def detect(self, frame):
        """BaseDetector contract: detect objects in frame and return list of Detection."""
        raw_func = type(self).detect_raw_objects
        if raw_func is not Detector.detect_raw_objects:
            raw = self.detect_raw_objects(frame)
            if not raw:
                return []
            detections = []
            for item in raw:
                if isinstance(item, TailItem):
                    b = item.bbox
                elif isinstance(item, (tuple, list)) and len(item) == 4:
                    b = tuple(item)
                elif is_numpy(item):
                    b = tuple(cv2.boundingRect(item))
                else:
                    continue
                detections.append(
                    Detection(
                        bbox=tuple(map(int, b)),
                        class_id=0,
                        confidence=1.0,
                        label=self.__class__.__name__,
                    )
                )
            return detections
        return []

    def filter_bad_raw_objects(self, tail_objects, frame, mask=None):
        return

    def _match_tail_to_objects(self, ti, active_objects_dic):
        """Check if tail item is inside or near any active object."""
        near_flag = False
        for o, (inside, _near) in active_objects_dic.items():
            if o.tail[0].point_inside(ti) or ti.point_inside(o.position):
                inside.append(ti)
                return True, False
            flag, _dist = o.tail[0].cnt_near(ti)
            if flag:
                near_flag = True
        return False, near_flag

    def process_raw_objects(self, frame, tail_items, bad_items, mask=None):
        """Create new objects or update existing active objects from tail items."""
        active_objects_dic = {i: ([], []) for i in self.active_objects()}
        unclassified = []

        for ti in tail_items:
            matched_inside, near_flag = self._match_tail_to_objects(ti, active_objects_dic)
            if not matched_inside and not near_flag and ti not in bad_items:
                o = Object(frame=frame, parent_detector=self, tail_item=ti, mask=mask)
                self.objects.add_as_contained(o)
                unclassified.append(o)

        for o, (inside, _near) in active_objects_dic.items():
            if not inside:
                if not o.is_tracking:
                    o._stray_count += 1
            else:
                cont = np.vstack(inside)
                hull = cv2.convexHull(cont)
                o.update_tracker(frame, cnt=hull)

        return unclassified

    def _compute_objects(
        self, frame, mask=None, track=True, _debug_good=None, _debug_bad=None
    ):
        """Complete steps to track, detect, and process objects."""
        if track:
            self.track_objects(frame, mask)
        raw_objects = self.detect_raw_objects(frame, mask)
        if raw_objects is None:
            return None

        raw_objects = [
            i if isinstance(i, TailItem) else TailItem(i) for i in raw_objects
        ]
        bad_objects = self.filter_bad_raw_objects(raw_objects, frame, mask)
        bad_set = set(bad_objects) if bad_objects is not None else set()

        if _debug_good is not None:
            self._debug_detector(
                _debug_good, [i for i in raw_objects if i not in bad_set]
            )
        if _debug_bad is not None:
            self._debug_detector(_debug_bad, bad_set)

        objs = self.process_raw_objects(frame, raw_objects, bad_set, mask)
        self.delete_stray_objects()
        return objs


class Detector(
    DetectorObjectLifecycleMixin,
    DetectorProcessingMixin,
    Space,
    BaseDetector,
):
    """Detector creates and tracks objects or entities in the scene."""

    available_detectors: dict[str, type] = {}

    def __init__(self):
        super().__init__()
        self._BGR_color = None
        self.objects = Group(_space_parent=self, name="objects")

    def get_BGR_color(self):
        """Get detector color inherited from parent detector or randomly generated."""
        if self._BGR_color is None:
            try:
                self._BGR_color = norm_range(self._space_parent.get_BGR_color())
            except AttributeError:
                self._BGR_color = norm_range(np.random.rand(3) * 255)
        return self._BGR_color

    @classmethod
    def register_detector(cls, detector_class: type, name: Optional[str] = None):
        """Register a Detector subclass in available_detectors and DetectorFactory."""
        if issubclass(detector_class, Detector) and detector_class is not Detector:
            if name is None:
                name = detector_class.__name__.lower()
            name_clean = name.lower()
            if name_clean in cls.available_detectors or name in cls.available_detectors:
                raise ValueError(f"name '{name}' is already registered")
            cls.available_detectors[name] = detector_class
            cls.available_detectors[name_clean] = detector_class
            DetectorFactory._registry[name_clean] = detector_class
        else:
            raise TypeError(f"class must be a subclass of {Detector}")

    @classmethod
    def get_detector(cls, name: str) -> type:
        """Retrieve a registered detector class by name."""
        name_clean = str(name).lower()
        if name in cls.available_detectors:
            return cls.available_detectors[name]
        if name_clean in cls.available_detectors:
            return cls.available_detectors[name_clean]
        if name_clean in DetectorFactory._registry:
            return DetectorFactory._registry[name_clean]
        available = sorted(
            set(list(cls.available_detectors.keys()) + DetectorFactory.available())
        )
        raise KeyError(
            f"name '{name}' is not registered. Available: {available}"
        )

    def _debug_detector(self, vis, mask):
        """Render debug detection masks onto visual canvas."""
        if not is_numpy(mask):
            cnts = [i.cnt if isinstance(i, TailItem) else i for i in mask]
            mask = draw_contour_groups([cnts], shape=vis.shape, binary=True)
        pallet = np.array([[0, 0, 0], self.get_BGR_color()])
        a = pallet[(mask > 0).astype(int)]
        vis[mask > 0] = (vis * 0.5 + a * 0.5)[mask > 0].astype(np.uint8)

    def __json_enco__(self):
        pass

