"""Trajectory history items, point structures, and geometric intersection tests."""

from collections import namedtuple

import cv2
import numpy as np
from scipy.spatial.distance import euclidean

from intelligent_tracker.core.agents import Agent
from intelligent_tracker.geometry import cnt_check_intersection

Point = namedtuple('Point', ('x', 'y', 'z'))


class TailItem:
    """TailItem(cnt, rbox, bbox, pt) which behaves like cnt"""
    # based from recordtype('TailItem', ['cnt', 'rbox', 'bbox', 'pt'])
    # why use __slots__
    #   https://stackoverflow.com/a/1816648/5288758

    _fields = ('cnt', 'rbox', 'bbox', 'pt')
    __slots__ = ["_" + i for i in _fields]

    def __init__(self, cnt=None, rbox=None, bbox=None, pt=None):
        if cnt is None and rbox is None and bbox is None:
            raise Exception("must provide at least cnt, rbox or bbox")
        self._cnt = cnt
        self._rbox = rbox
        if bbox is not None:
            bbox = tuple(bbox)
        self._bbox = bbox
        if pt is not None and not isinstance(pt, Point):
            pt = Point(*pt)  # must be iterable
        self._pt = pt

    def point_inside(self, point):
        """
        test whether point is inside contour

        :param point: point or x-coordinate, y-coordinate
        :return: True if inside or the border of contour, else False
        """
        try:
            return cv2.pointPolygonTest(self.cnt, point.pt[:2], False) != -1
        except AttributeError:
            return cv2.pointPolygonTest(self.cnt, point[:2], False) != -1

    def cnt_intersect(self, cnt):
        """
        test whether internal cnt is intersected with external cnt

        :param cnt: external contour
        :return: True if contours intersect, else False
        """
        try:
            return cnt_check_intersection(self.cnt, cnt.cnt)  # TailItem object
        except AttributeError:
            return cnt_check_intersection(self.cnt, cnt)

    def cnt_near(self, cnt, min_dist=None):
        try:
            (x2, y2), r2 = cnt.enclosing_circle()  # TailItem object
        except AttributeError:
            (x2, y2), r2 = cv2.minEnclosingCircle(cnt)
        (x1, y1), r1 = self.enclosing_circle()
        if min_dist is None:
            min_dist = (r1 + r2) / 2.
        row1 = ((x1 - r1, y1), (x1, y1 + r1), (x1 + r1, y1), (x1, y1 - r1))
        row2 = ((x2 - r2, y2), (x2, y2 + r2), (x2 + r2, y2), (x2, y2 - r2))
        min_dt = np.inf
        for i in row1:
            for j in row2:
                dt = euclidean(i, j)
                if dt < min_dt:
                    min_dt = dt
                if dt < min_dist:
                    return True, min_dt
        return False, min_dt

    def point_near(self, point, min_dist=50):
        try:
            pt = point.pt[:2]  # TailItem object
        except AttributeError:
            pt = point[:2]
        (x1, y1), r1 = self.enclosing_circle()
        if min_dist is None:
            min_dist = r1
        row1 = ((x1 - r1, y1), (x1, y1 + r1), (x1 + r1, y1), (x1, y1 - r1))
        min_dt = np.inf
        for i in row1:
            dt = euclidean(i, pt)
            if dt < min_dt:
                min_dt = dt
            if dt < min_dist:
                return True, min_dt
        return False, min_dt

    def enclosing_circle(self):
        # ((x, y), radius)
        return cv2.minEnclosingCircle(self.cnt)

    @property
    def cnt(self):
        if self._cnt is None:
            if self._rbox is not None:
                self._cnt = Agent.get_cnt_from_rotated_box(self._rbox)
            elif self._bbox is not None:
                self._cnt = Agent.get_cnt_from_bounding_box(self._bbox)
            else:
                raise RuntimeError("no enough information")
        return self._cnt

    @property
    def rbox(self):
        if self._rbox is None:
            if self._cnt is not None:
                self._rbox = Agent.get_rotated_box_from_cnt(self._cnt)
            elif self._bbox is not None:
                self._rbox = Agent.get_rotated_box_from_bounding_box(self._bbox)
            else:
                raise RuntimeError("no enough information")
        return self._rbox

    @property
    def bbox(self):
        if self._bbox is None:
            if self._cnt is not None:
                self._bbox = Agent.get_bounding_box_from_cnt(self._cnt)
            elif self._rbox is not None:
                self._bbox = Agent.get_bounding_box_from_rotated_box(self._rbox)
            else:
                raise RuntimeError("no enough information")
        return self._bbox

    @property
    def pt(self):
        if self._pt is None:
            M = cv2.moments(self.cnt)
            z = M["m00"]
            try:
                x, y = (int(M["m10"] / M["m00"]),
                        int(M["m01"] / M["m00"]))
            except ZeroDivisionError:
                # FIXME zerodivision
                print("ZeroDivisionError with cnt", self.cnt)
                raise
            self._pt = Point(x, y, z)
        return self._pt

    # cnt behaviour
    def __len__(self):
        return len(self.cnt)

    def __iter__(self):
        for i in self.cnt:
            yield i

    def __getitem__(self, index):
        return self.cnt[index]

    def __eq__(self, other):
        return (isinstance(other, self.__class__) and self.cnt == other.cnt
                and self.rbox == other.rbox and self.bbox == other.bbox
                and self.pt == other.pt)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return id(self)

    # others
    def _asdict(self):
        return {'cnt': self.cnt, 'rbox': self.rbox, 'bbox': self.bbox,
                'pt': self.pt}

    def __repr__(self):
        return "{cn}(cnt={cnt}, rbox={rbox}, bbox={bbox}, pt={pt})".format(
            cn=self.__class__.__name__, **self._asdict())

    # persistence
    def __getstate__(self):
        return (self._cnt, self._rbox, self._bbox, self._pt)

    def __setstate__(self, state):
        (self._cnt, self._rbox, self._bbox, self._pt) = state

