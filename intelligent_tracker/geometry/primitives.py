"""Geometric primitives, coordinate normalization, and segment intersection math."""

import numpy as np
import cv2


class NotInvertible(Exception):
    """Exception to determine if an object is not invertible"""
    pass


class IncompleteAssociations(Exception):
    """Exception to raise when a connection could not be determined"""
    pass


def norm_point(pt):
    """Normalize point to a tuple (x,y) of native floats for cv2 compatibility."""
    arr = np.asarray(pt).reshape(2)
    return float(arr[0]), float(arr[1])


def bezier(point, line, check=False):
    """Apply bezier algorithm to return a value t from 0 to 1 in x and y,
    that is tx and ty, if point is inside line where t would be the
    percentage of the distance from point1 to point2. If point
    is outside line then t<0 or t>1. If line is horizontal then ty is not
    percentage but the distance from the horizontal and conversely if line
    is vertical then tx is not percentage but the distance from the vertical.

    :param point: point
    :param line: (point1, point2)
    :param check: True to check tx and ty and return None if point is not
        between point1 and point2 in the line.
    :return: tx, ty
    """
    px, py = point
    ((x1, y1), (x2, y2)) = line
    dx = (x1 - x2)
    dy = (y1 - y2)
    # check point is inside lines using Bézier parameters
    # https://en.wikipedia.org/wiki/B%C3%A9zier_curve#Linear_curves
    # dx and dy are 0 then line is not a line but a point
    tx = x1 - px
    if dx != 0:
        # in x for line 1
        tx /= dx
        if check and not 0 <= tx <= 1:
            return None
    elif check and px != x1:
        # if dx = 0 then x1 = x2
        return None

    ty = y1 - py
    if dy != 0:
        # in y for line 1
        ty /= dy
        if check and not 0 <= ty <= 1:
            return None
    elif check and py != y1:
        # if dy = 0 then y1 = y2
        return None

    # if it passed the tests then return True
    return tx, ty


def line_intersection(line1, line2, check_inside=True):
    """Find the intersecting point between two lines.

    :param line1: (line1_point1, line1_point2)
    :param line2: (line2_point1, line2_point2)
    :param check_inside: if True and the lines do not cross
        between their points then it is not considered an intersection
        and None is returned
    :return: point
    """
    # https://en.wikipedia.org/wiki/Line%E2%80%93line_intersection
    ((x1, y1), (x2, y2)) = line1
    ((x3, y3), (x4, y4)) = line2
    L2_dx, L1_dx = (x3 - x4), (x1 - x2)
    L2_dy, L1_dy = (y3 - y4), (y1 - y2)
    det_denominator = L1_dx * L2_dy - L1_dy * L2_dx
    # When the two lines are parallel or coincident the denominator is zero
    if det_denominator == 0:
        return None
    # get numerators
    A = (x1 * y2 - y1 * x2)
    B = (x3 * y4 - y3 * x4)
    det_1 = A * L2_dx - L1_dx * B
    det_2 = A * L2_dy - L1_dy * B

    # get intersection point
    px = det_1 / det_denominator
    py = det_2 / det_denominator

    if (not check_inside or check_inside
            and bezier((px, py), line1, check=True)
            and bezier((px, py), line2, check=True)):
        # return intersection point
        return px, py
    return None


def cnt_group(cnt, cnt_cmp, check=False):
    """Compare cnt pertaining points and give the transitions.

    :param cnt: testing cnt
    :param cnt_cmp: comparing cnt
    :param check: True to return immediately if a point from cnt is found
        inside cnt_cmp and with the found flag added to the returned values,
        True for found or False for not found and consequently with all the
        flags and transitions plus the found flag.
    :return: (flags, transitions) where flags are 1 when the points from
        cnt which are in cnt_cmp, 0 when when in the contour and -1 when
        they are not inside. The flag is determined by pointPolygonTest.
        transitions is an list of the indices where a flag changes from
        outside to inside or in the contour and vice versa.
        if check is True: (flags, transitions, found)
    """
    assert len(cnt) > 1, "contour must have at least 2 points to test transitions"
    transitions = []
    flags = np.empty(len(cnt), int)
    pt_last = norm_point(cnt[-1])
    old_flag = cv2.pointPolygonTest(cnt_cmp, pt_last, False)
    for i, pt in enumerate(cnt):
        flags[i] = flag = cv2.pointPolygonTest(cnt_cmp, norm_point(pt), False)
        # border flag=0 is considered inside flag=1
        # so there is no transition from flag=0 to flag=1 or vice-versa
        # but from flag=0 to flag=-1 or flag=1 to flag=-1, or vice-versa
        if (flag == -1 and old_flag != -1) or (old_flag == -1 and flag != -1):
            # store where is the transition
            transitions.append(i)
        if check and flag != -1:
            # return until flag was found
            return flags[:i + 1], transitions, True
        # update flag
        old_flag = flag
    if check:
        return flags, transitions, False
    return flags, transitions


def go_around(index, size, negative=False):
    """Correct index to infinitely go around an array. This is equivalent
    to corrected_index = (index % size) but this function offers more
    control.

    :param index: index to correct
    :param size: size of array
    :param negative: True to not correct negative indexes
    :return: (flag, corrected_index) flag indicating that index was corrected
    """
    if not negative or index > size - 1 or index + size < 0:
        new_index = index % size
    else:
        new_index = index

    if index != new_index:
        return True, new_index
    return False, new_index


def segments_intersect(p1, p2, p3, p4):
    """Test whether line segment p1-p2 intersects line segment p3-p4.
    Points are (x, y) tuples.
    """
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (c[0] - a[0]) * (b[1] - a[1])

    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)

    # General intersection case
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    return False

