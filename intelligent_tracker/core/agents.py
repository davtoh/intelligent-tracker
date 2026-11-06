"""Spatial agent representation with visual bounding boxes, rotated boxes, and contours."""

import cv2
import numpy as np

from intelligent_tracker.core.spaces import Space


class Agent(Space):
    """
    Anything in the World with an individual behaviour which is movable and
    cannot be in more than one place at a time, that is and Agent. They
    can be observable and have positions in the Space. From here
    anything is derived and populated in the world.
    """
    def __init__(self):
        self._to_compute = True
        self.active = True
        self.visible = True
        self.drawing = None
        self.cnt = None
        self.rotated_box = None

    def _compute(self):
        """
        function executed when internal data must be updated
        """
        self._to_compute = False
        return

    def compute(self):
        """
        update internal data if necessary

        :return True if computed, else false
        """
        if self._to_compute:
            # compute
            self._compute()
        # if computed
        return not self._to_compute

    def computed_vis(self):
        pass

    def raw_vis(self):
        pass

    @staticmethod
    def get_bounding_box_from_cnt(cnt, _type=None):
        return Agent.get_bounding_box_from_rotated_box(
            Agent.get_rotated_box_from_cnt(cnt), _type)

    @staticmethod
    def get_bounding_box_from_rotated_box(rotated_box, _type=None):
        (tx, ty), (sz_x, sz_y), angle = rotated_box
        # get half distance to center
        x, y = sz_x / 2., sz_y / 2.
        if _type is None:
            return tx - x, ty - y, sz_x, sz_y
        else:
            return _type(tx - x), _type(ty - y), _type(sz_x), _type(sz_y)

    @staticmethod
    def get_rotated_box_from_cnt(cnt, _type=None):
        """
        get a rotated box format (center, size, angle)
        from a contour of N points.
        """
        if _type is None:
            return cv2.minAreaRect(cnt)
        else:
            (cx, cy), (x, y), a = cv2.minAreaRect(cnt)
            return (_type(cx), _type(cy)), (_type(x), _type(y)), _type(a)

    @staticmethod
    def get_rotated_box_from_bounding_box(bounding_box, _type=None):
        x, y, sz_x, sz_y = bounding_box
        # get half distance to center
        tx, ty = sz_x / 2., sz_y / 2.
        if _type is None:
            return (x + tx, y + ty), (sz_x, sz_y), 0
        else:
            return ((_type(x + tx), _type(y + ty)),
                    (_type(sz_x), _type(sz_y)), _type(0))

    @staticmethod
    def get_cnt_from_rotated_box(rotated_box, _type=np.int32):
        """
        get a contour of 4 points with format [left-top, right-top,
        right-bottom, left-bottom] from a rotated box with format
        (center, size, angle)
        """
        # format (x,y),(width,height),theta e.g. ((122, 239), (4, 4), 0)
        (tx, ty), (sz_x, sz_y), angle = rotated_box
        # get half distance to center
        x, y = sz_x / 2., sz_y / 2.
        # construct contour in origin
        cnt_rect = np.array([((-x, -y),), ((x, -y),),
                             ((x, y),), ((-x, y),)], float)

        # create transformation matrix to rotate and translate
        # https://en.wikipedia.org/wiki/Transformation_matrix
        a = angle * np.pi / 180.  # convert from degrees to radians
        c = np.cos(a)
        s = np.sin(a)
        H = np.array([(c, -s, tx),
                      (s, c, ty),
                      (0, 0, 1)], float)

        # apply transformation with desired type
        # https://docs.opencv.org/2.4/modules/core/doc/operations_on_arrays.html#perspectivetransform
        if _type is None:
            return cv2.perspectiveTransform(cnt_rect, H)
        else:
            return _type(cv2.perspectiveTransform(cnt_rect, H))

    @staticmethod
    def get_cnt_from_bounding_box(bounding_box, _type=np.int32):
        return Agent.get_cnt_from_rotated_box(
            Agent.get_rotated_box_from_bounding_box(bounding_box), _type)

    def __json_enco__(self):
        pass

