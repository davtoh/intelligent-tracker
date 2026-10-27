#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# import built-in modules
import os
import abc
from collections import deque, namedtuple
from typing import List, Tuple, Optional, Any, Dict

# import third party modules
#from RRtoolbox.lib.plotter import fastplt  # DEBUG
#from RRtoolbox.lib.arrayops import overlay
from .core import Space, Group, Agent, cv_major_ver, xrange, TailItem, Point
from .array_utils import norm_range, draw_contour_groups, is_numpy
import numpy as np
import cv2

# special variables
__all__ = [
    'Detection', 'BaseDetector', 'Detector', 'DetectorFactory',
    'HaarCascadeDetector', 'FaceDetector', 'YuNetFaceDetector', 'EyeDetector', 'ColorDetector',
    'MockDetector', 'OnnxDetector', 'EdgeTpuDetector', 'COCO_CLASSES', 'Object'
]
__author__ = "David Toro"
# __copyright__ = "Copyright 2017, The <name> Project"
# __credits__ = [""]
__license__ = "GPL"
# __version__ = "1.0.0"
__maintainer__ = "David Toro"
__email__ = "davsamirtor@gmail.com"
# __status__ = "Pre-release"

SCRIPT_PATH = os.path.dirname(os.path.realpath(__file__))  # get current file path
LOCAL_HAARCASCADES = os.path.abspath(os.path.join(SCRIPT_PATH, "haarcascades"))
if hasattr(cv2, 'data') and hasattr(cv2.data, 'haarcascades') and os.path.isfile(os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')):
    DETECTOR_PATH = cv2.data.haarcascades
else:
    DETECTOR_PATH = LOCAL_HAARCASCADES
face_cascade = cv2.CascadeClassifier(os.path.abspath(os.path.join(DETECTOR_PATH, 'haarcascade_frontalface_default.xml')))
eye_cascade = cv2.CascadeClassifier(os.path.abspath(os.path.join(DETECTOR_PATH, 'haarcascade_eye.xml')))

Detection = namedtuple('Detection', ['bbox', 'class_id', 'confidence', 'label'])


class BaseDetector(abc.ABC):
    """
    Abstract Base Detector defining the modern Edge AI detection interface.
    """
    @abc.abstractmethod
    def detect(self, frame):
        """
        Detect objects in a BGR image frame.

        :param frame: numpy array (H, W, 3) BGR format
        :return: list of Detection(bbox=(x, y, w, h), class_id=int, confidence=float, label=str)
        """
        raise NotImplementedError


class DetectorFactory:
    """
    Registry and factory for creating detectors by name from configuration or CLI.
    Supports 'haar', 'yolov8', 'yolo11', 'mock', 'color', 'face', 'eye', etc.
    """
    _registry = {}

    @classmethod
    def register(cls, name, detector_class):
        name_clean = name.lower().strip()
        cls._registry[name_clean] = detector_class
        try:
            if isinstance(detector_class, type) and issubclass(detector_class, Detector) and detector_class is not Detector:
                Detector.available_detectors[name_clean] = detector_class
        except (NameError, TypeError):
            pass

    @classmethod
    def available(cls):
        return sorted(list(cls._registry.keys()))

    @classmethod
    def create(cls, name, *args, **kwargs):
        name_clean = str(name).lower().strip()
        if name_clean not in cls._registry:
            raise KeyError("Detector '{}' is not registered. Available: {}".format(
                name, cls.available()))

        target = cls._registry[name_clean]
        if callable(target):
            return target(*args, **kwargs)
        raise TypeError("Registered detector for '{}' is not callable".format(name))


class Detector(Space, BaseDetector):
    """
    Here a Detector creates an Object or Entity from the real world
    which will have its own behaviour or "personality". This Detector is
    the one that classifies the objects and finds them in the real world
    if they are "lost" or they are not in the scenes anymore until
    they reappear again.
    """
    available_detectors = {}

    def __init__(self):
        # private Detector color
        self._BGR_color = None
        self.objects = Group(_space_parent=self, name="objects")

    def active_objects(self):
        """
        :return: objects that are active regardless if they are tracking
        """
        for o in self.objects:
            if o.active:
                yield o

    def inactive_objects(self):
        """
        :return: objects that are not active
        """
        for o in self.objects:
            if not o.active:
                yield o

    def tracked_objects(self):
        """
        :return: objects that are active and are tracking
        """
        for o in self.objects:
            if o.active and o.is_tracking:
                yield o

    def untracked_objects(self):
        """
        :return: objects that are not active or are not tracking
        """
        for o in self.objects:
            if not o.active or not o.is_tracking:
                yield o

    def track_objects(self, frame, mask=None):
        """
        only update without creating new objects

        :param frame:
        :param mask:
        :return:
        """
        for o in self.objects:
            if o.active:
                o.update(frame, mask)

    def detect_raw_objects(self, frame, mask=None):
        """To modify behaviour of detection"""
        detect_func = type(self).detect
        if detect_func is not Detector.detect:
            detections = self.detect(frame)
            if detections:
                return [TailItem(bbox=d.bbox) for d in detections]
        return None

    def detect(self, frame):
        """
        BaseDetector contract: detect objects in frame and return list of Detection namedtuples.
        """
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
                detections.append(Detection(bbox=tuple(map(int, b)),
                                            class_id=0,
                                            confidence=1.0,
                                            label=self.__class__.__name__))
            return detections
        return []

    def filter_bad_raw_objects(self, tail_objects, frame, mask=None):
        return

    def process_raw_objects(self, frame, tail_items, bad_items, mask=None):
        """
        create new object or reuse object from a tail_item

        :param frame:
        :param tail_items:
        :param mask:
        :return:
        """
        #TODO objects should not be created inside other objects
        #FIXME if object dissappears from a period of time it is deleted but it should be restored (solve: do not touch o._stray_count but device a mechanism to move object to that new position)
        #TODO needs to implement the features of obejcts. This process should be paralell
        #TODO needs to implement paralelization of obejcts so that it does not take a lot of time if objects are increased

        # create dictionary to classify
        # format (inside, near)
        active_objects_dic = {i:([],[]) for i in self.active_objects()}
        # unclassified
        unclassified = []

        # classify all tail_items with objects
        for ti in tail_items:
            near_flag = False
            for o, (inside, near) in active_objects_dic.items():
                # find out if cnt overlaps with objects from this detector
                # faster check
                if o.tail[0].point_inside(ti):
                    # tail_item inside Object
                    # do not let object tracker grow too much
                    #o.update_tracker(frame, tail_item=ti)
                    inside.append(ti)
                    break
                elif ti.point_inside(o.position):
                    # Object inside tail_item
                    # if object lost track and it was detected again
                    #o.update_tracker(frame, tail_item=ti)
                    inside.append(ti)
                    break
                #elif o.tail[0].cnt_intersect(ti):  # covered by cnt_near
                #    # Object and tail_item touch
                #    break
                else:
                    flag, dist = o.tail[0].cnt_near(ti)
                    if flag:
                        # it is near an object do not create new
                        near_flag = True

                        # append to near raw_objects of object
                        #near.append(ti)

                        # continue finding objects that could contain the raw_obejct
                        continue
            else:
                if not near_flag and ti not in bad_items:
                    # create new object only if raw_object is not any of the
                    # objects that are being tracked
                    o = Object(frame=frame, parent_detector=self,
                               tail_item=ti, mask=mask)
                    self.objects.add_as_contained(o)
                    unclassified.append(o)

        # create or reuse objects as needed
        #for ti in unclassified:
        #    o = Object(frame=frame, parent_detector=self,
        #               tail_item=ti, mask=mask)
        #    self.objects.add_as_contained(o)
        for o, (inside, near) in active_objects_dic.items():
            if not inside:
                if not o.is_tracking:
                    o._stray_count += 1
            else:
                # group tail items and update tracker
                cont = np.vstack(inside)
                hull = cv2.convexHull(cont)
                o.update_tracker(frame, cnt=hull)

        return unclassified

    def delete_stray_objects(self):
        """
        delete all objects that are missing the correct target
        """
        objects = self.objects
        for o in objects:
            if (o.active and not o.live_forever and
                        o._stray_count > o._max_stray_count):
                o._space_delete()  # delete from all groups

    def _compute_objects(self, frame, mask=None, track=True, _debug_good=None,
                         _debug_bad=None):
        """
        complete steps to detect and process objects

        :param frame:
        :param mask:
        :param track:
        :param _debug_good:
        :return:
        """
        # example code
        if track:
            self.track_objects(frame, mask)
        # get raw objects from frame
        raw_objects = self.detect_raw_objects(frame, mask)

        # if there are raw objects to process
        if raw_objects is not None:

            # convert raw_objects items to tail items if not already
            raw_objects = [i if isinstance(i, TailItem) else TailItem(i)
                            for i in raw_objects]

            # filter raw_objects if necessary
            bad_objects = self.filter_bad_raw_objects(raw_objects, frame, mask)
            if bad_objects is None:
                bad_objects = set()
            else:
                bad_objects = set(bad_objects)  # for fast membership

            # debug good raw_objects
            if _debug_good is not None:
                self._debug_detector(_debug_good, [i for i in raw_objects
                                                   if i not in bad_objects])

            # debug bad raw_objects
            if _debug_bad is not None:
                self._debug_detector(_debug_bad, bad_objects)

            # process tail item into an object
            objs = self.process_raw_objects(frame, raw_objects, bad_objects, mask)

            # delete all objects that are missing the correct target
            self.delete_stray_objects()

            return objs

    def get_BGR_color(self):
        """
        get detector color from Parent detector or randomly generated
        """
        if self._BGR_color is None:
            try:
                # inherit color from parent
                self._BGR_color = norm_range(self._space_parent.get_BGR_color())
            except AttributeError:
                self._BGR_color = norm_range(np.random.rand(3)*255)
        return self._BGR_color

    @classmethod
    def register_detector(cls, detector_class, name=None):
        if issubclass(detector_class, Detector) and detector_class is not Detector:
            if name is None:
                name = detector_class.__name__.lower()
            name_clean = name.lower()
            if name_clean in cls.available_detectors or name in cls.available_detectors:
                raise ValueError("name '{}' is already registered".format(name))
            cls.available_detectors[name] = detector_class
            cls.available_detectors[name_clean] = detector_class
            DetectorFactory._registry[name_clean] = detector_class
        else:
            raise TypeError("class must be a subclass of {}".format(Detector))

    @classmethod
    def get_detector(cls, name):
        name_clean = str(name).lower()
        if name in cls.available_detectors:
            return cls.available_detectors[name]
        if name_clean in cls.available_detectors:
            return cls.available_detectors[name_clean]
        if name_clean in DetectorFactory._registry:
            return DetectorFactory._registry[name_clean]
        available = sorted(set(list(cls.available_detectors.keys()) + DetectorFactory.available()))
        raise KeyError("name '{}' is not registered. Available: {}".format(name, available))

    def __json_enco__(self):
        pass

    def _debug_detector(self, vis, mask):
        # construct a mask if mask is cnts
        if not is_numpy(mask):
            cnts = [i.cnt if isinstance(i, TailItem) else i for i in mask]
            mask = draw_contour_groups([cnts], shape=vis.shape, binary=True)
        pallet = np.array([[0, 0, 0], self.get_BGR_color()])
        a = pallet[(mask > 0).astype(int)]
        # a = np.zeros_like(frame)
        # a[mask>0] = color
        vis[mask > 0] = (vis * 0.5 + a * 0.5)[mask > 0].astype(np.uint8)


def affine(phi, img):
    """
    Increase robustness to descriptors by calculating other invariant perspectives to image.

    :param phi: rotation of image (in degrees)
    :param img: image to find Affine transforms
    :param mask: mask to detect keypoints (it uses default, mask[:] = 255)
    :return: skew_img, skew_mask, Ai (invert Affine Transform)

    Ai - is an affine transform matrix from skew_img to img

    """
    h, w = img.shape[:2]  # get 2D shape
    A = np.float32([[1, 0, 0], [0, 1, 0]])  # init Transformation matrix
    if phi != 0.0:  # simulate rotation
        phi = np.deg2rad(phi)  # convert degrees to radian
        s, c = np.sin(phi), np.cos(phi)  # get sine, cosine components
        # build partial Transformation matrix
        A = np.float32([[c, -s], [s, c]])
        corners = [[0, 0], [w, 0], [w, h], [0, h]]  # use corners
        tcorners = np.int32(np.dot(corners, A.T))  # transform corners
        x, y, w, h = cv2.boundingRect(
            tcorners.reshape(1, -1, 2))  # get translations
        A = np.hstack([A, [[-x], [-y]]])  # finish Transformation matrix build
        img = cv2.warpAffine(
            img, A, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

        h, w = img.shape[:2]  # get new 2D shape
    Ai = cv2.invertAffineTransform(A)
    return img, Ai


class InvariantCascade:

    def __init__(self, angles=None):
        self.angles = angles

    def transformations(self, frame):
        #cols, rows = frame.shape[:2]
        for angle in self.angles:
            #angle = angle*np.pi/180
            #x, y = float(frame.shape[0])/2, float(frame.shape[1])/2
            #M = cv2.getRotationMatrix2D((y, x), angle, 1)
            #cols2, rows2 = np.dot(M, (cols, rows, 1))
            #M = np.array(((np.cos(angle), np.sin(angle), 0), (-np.sin(angle), np.cos(angle), 0)))
            #yield M, angle, cv2.warpAffine(frame, M, (int(cols2), int(rows2)))
            img, Ai = affine(angle, frame)
            yield Ai, angle, img

    def reconstruct(self, Ai, angle, bbox):
        #H = np.linalg.inv(np.append(M, ((0, 0, 1),), 0))
        # TODO: virtual coordinates not with real coordinates
        x, y, sz_x, sz_y = bbox
        xn, yn = np.dot(Ai, (x, y, 1))
        return Agent.get_rotated_box_from_bounding_box((xn, yn, sz_x, sz_y))[:-1]+(-angle,)


class HaarCascadeDetector(Detector):
    """
    Haar cascade classifier wrapped as a concrete BaseDetector subclass.
    """
    def __init__(self, cascade_path=None, scale_factor=1.3, min_neighbors=5,
                 min_size=(30, 30), max_size=None, label='haar_object'):
        super(HaarCascadeDetector, self).__init__()
        if cascade_path is None:
            cascade_path = os.path.abspath(os.path.join(DETECTOR_PATH, 'haarcascade_frontalface_default.xml'))
        elif not os.path.isabs(cascade_path):
            p = os.path.abspath(os.path.join(DETECTOR_PATH, cascade_path))
            if os.path.isfile(p):
                cascade_path = p
        self.cascade_path = cascade_path
        self.cascade = cv2.CascadeClassifier(cascade_path)
        self.scale_factor = scale_factor
        self.min_neighbors = min_neighbors
        self.min_size = min_size
        self.max_size = max_size
        self.label = label

    def detect(self, frame):
        if frame is None or getattr(frame, 'size', 0) == 0 or self.cascade.empty():
            return []
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        elif len(frame.shape) == 3 and frame.shape[2] == 4:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        else:
            gray = frame

        kwargs = {'scaleFactor': self.scale_factor, 'minNeighbors': self.min_neighbors}
        if self.min_size:
            kwargs['minSize'] = self.min_size
        if self.max_size:
            kwargs['maxSize'] = self.max_size

        rects = self.cascade.detectMultiScale(gray, **kwargs)
        if len(rects) == 0:
            return []

        return [Detection(bbox=tuple(map(int, r)), class_id=0, confidence=1.0, label=self.label)
                for r in rects]

    def detect_raw_objects(self, frame, mask=None):
        detections = self.detect(frame)
        return [TailItem(bbox=d.bbox) for d in detections]

Detector.register_detector(HaarCascadeDetector)


class EyeDetector(HaarCascadeDetector):
    def __init__(self, **kwargs):
        eye_xml = os.path.abspath(os.path.join(DETECTOR_PATH, 'haarcascade_eye.xml'))
        kwargs.setdefault('cascade_path', eye_xml)
        kwargs.setdefault('label', 'eye')
        super(EyeDetector, self).__init__(**kwargs)

    def detect_raw_objects(self, frame, mask=None):
        min_size = 0.1
        max_size = 0.5
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # http://answers.opencv.org/question/116587/rejectlevels-and-levelweights-of-detectmultiscale/
        eyes = eye_cascade.detectMultiScale(gray,
                                            minSize=(int(w * min_size),
                                                     int(h * min_size)),
                                            maxSize=(int(w * max_size),
                                                     int(h * max_size)),
                                            flags=cv2.CASCADE_SCALE_IMAGE)

        return [TailItem(bbox=bbox) for bbox in eyes]

Detector.register_detector(EyeDetector)


class FaceDetector(HaarCascadeDetector):
    def __init__(self, **kwargs):
        face_xml = os.path.abspath(os.path.join(DETECTOR_PATH, 'haarcascade_frontalface_default.xml'))
        kwargs.setdefault('cascade_path', face_xml)
        kwargs.setdefault('label', 'face')
        super(FaceDetector, self).__init__(**kwargs)

    def detect_raw_objects(self, frame, mask=None):
        min_scale = 0.05  # 0.1
        h, w = frame.shape[:2]
        minSize = (int(w * min_scale), int(h * min_scale))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        normal = []
        to_rotate = InvariantCascade([0, 20, 40, -20, -40])
        for M, i, f in to_rotate.transformations(gray):
            faces = face_cascade.detectMultiScale(f, minSize=minSize,
                                                  scaleFactor=1.3,
                                                  minNeighbors=5,
                                                  flags=cv2.CASCADE_SCALE_IMAGE)

            normal.extend([TailItem(rbox=to_rotate.reconstruct(M, i, bbox)) for bbox in faces])

        return normal

Detector.register_detector(FaceDetector)


class YuNetFaceDetector(BaseDetector):
    """
    ONNX-based YuNet face detector utilizing OpenCV's cv2.FaceDetectorYN.
    Provides sub-millisecond, highly robust face localization with facial landmark awareness.
    Automatically cascades to HaarCascadeDetector if the ONNX model file or FaceDetectorYN
    is unavailable in the runtime environment.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
        **kwargs,
    ):
        super().__init__()
        self.conf_threshold = float(conf_threshold)
        self.nms_threshold = float(nms_threshold)
        self.top_k = int(top_k)
        self._detector = None
        self._fallback = None

        resolved = self._resolve_model_path(model_path)
        if resolved and hasattr(cv2, "FaceDetectorYN"):
            try:
                self._detector = cv2.FaceDetectorYN.create(
                    model=resolved,
                    config="",
                    input_size=(320, 320),
                    score_threshold=self.conf_threshold,
                    nms_threshold=self.nms_threshold,
                    top_k=self.top_k,
                )
                self.model_path = resolved
            except Exception:
                self._detector = None

        if self._detector is None:
            self._fallback = FaceDetector(**kwargs)
            self.model_path = getattr(self._fallback, "cascade_path", "haar_fallback")

    @staticmethod
    def _resolve_model_path(path: Optional[str]) -> Optional[str]:
        if path and os.path.isfile(path):
            return os.path.abspath(path)
        candidates = [
            "models/face_detection_yunet_2023mar.onnx",
            "models/yunet.onnx",
            os.path.join(os.path.dirname(__file__), "..", "models", "face_detection_yunet_2023mar.onnx"),
            os.path.join(os.path.dirname(__file__), "..", "models", "yunet.onnx"),
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return os.path.abspath(c)
        return None

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if frame is None or getattr(frame, "size", 0) == 0:
            return []

        if self._detector is not None:
            h, w = frame.shape[:2]
            if w < 2 or h < 2:
                return []
            self._detector.setInputSize((w, h))
            ret, faces = self._detector.detect(frame)
            if faces is None or len(faces) == 0:
                return []

            results = []
            for face in faces:
                bx, by, bw, bh = int(face[0]), int(face[1]), int(face[2]), int(face[3])
                score = float(face[-1])
                # Clamp coordinates to frame boundaries
                bx = max(0, min(bx, w - 1))
                by = max(0, min(by, h - 1))
                bw = max(1, min(bw, w - bx))
                bh = max(1, min(bh, h - by))

                results.append(Detection(
                    bbox=(bx, by, bw, bh),
                    class_id=0,
                    confidence=score,
                    label="face",
                ))
            return results

        if self._fallback is not None:
            return self._fallback.detect(frame)

        return []



class PeopleDetector(Detector):
    pass

Detector.register_detector(PeopleDetector)


class ObjectDetector(Detector):
    pass

Detector.register_detector(ObjectDetector)


class MovementDetector(Detector):
    pass

Detector.register_detector(MovementDetector)


class ColorDetector(Detector):
    """
    Detect objects by color
    """

    def __init__(self, color_lower, color_upper):
        super(ColorDetector, self).__init__()
        self.color_lower = norm_range(color_lower)
        self.color_upper = norm_range(color_upper)

    def get_HSV_color_range(self):
        """
        return lower and upper HSV ranges
        """
        return self.color_lower, self.color_upper

    def set_HSV_color_range(self, color_lower=None, color_upper=None):
        """
        set lower and upper HSV ranges
        """
        if color_lower:
            self.color_lower = norm_range(color_lower)
        if color_upper:
            self.color_upper = norm_range(color_upper)

    def get_HSV_color(self):
        """
        return media HSV color from lower and upper HSV ranges
        """
        lower, upper = self.get_HSV_color_range()
        lower, upper = np.array(lower), np.array(upper)
        return (lower+upper)/2

    def get_BGR_color(self):
        """
        return media BGR color from lower and upper HSV ranges
        """
        return cv2.cvtColor(np.array([[self.get_HSV_color()]], np.uint8),
                            cv2.COLOR_BGR2HSV)[0, 0]

    def detect_raw_objects(self, frame, mask=None):
        blurred = cv2.GaussianBlur(frame, (11, 11), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

        # construct a mask for the color, then perform a series of dilation
        # and erosion operations to remove any small blobs left in it
        mk = cv2.inRange(hsv, self.color_lower, self.color_upper)
        mk = cv2.erode(mk, None, iterations=2)
        mk = cv2.dilate(mk, None, iterations=2)

        # find contours in the mask and initialize the current
        # (x, y) center of the ball
        cnts = cv2.findContours(mk, cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE)[-2]
        return cnts

    def filter_bad_raw_objects(self, tail_objects, frame, mask=None):
        # only proceed if at least one contour was found
        ignore = False
        ignore_z = 0.001  # percent
        #z_must_be = np.min(frame.shape[:2])/ignore_z  # z as radius
        z_must_be = frame.shape[0]*frame.shape[1]*ignore_z  # z as area
        bad_objects = []
        for ti in tail_objects:
            #((x, y), z) = cv2.minEnclosingCircle(cnt)  # z as radius
            M = cv2.moments(ti.cnt)
            z = M["m00"]  # z as area
            x, y = (int(M["m10"] / M["m00"]),
                    int(M["m01"] / M["m00"]))
            # complete more data in tail item
            ti._pt = Point(*(x, y, z))

            if mask is not None:
                # find out if cnt overlaps with objects from other detectors
                #ignore = mask[y, x]
                pass

            # only proceed if cnt is not covered by other trackers
            # and z meets a minimum size
            if ignore and z < z_must_be:
                bad_objects.append(ti)
        return bad_objects

    def detect(self, frame):
        cnts = self.detect_raw_objects(frame)
        if not cnts:
            return []
        detections = []
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            detections.append(Detection(bbox=(int(x), int(y), int(w), int(h)),
                                        class_id=0,
                                        confidence=1.0,
                                        label='color_object'))
        return detections

    @classmethod
    def __json_deco__(cls, data):
        return cls(data[0], data[1])

    def __json_enco__(self):
        return self.get_HSV_color_range()

Detector.register_detector(ColorDetector)


class MockDetector(Detector):
    """
    Mock detector for CI, unit testing, and headless execution.
    Generates synthetic or deterministic bounding boxes without requiring hardware or models.
    """
    def __init__(self, boxes=None, class_id=0, confidence=0.95, label='mock_person',
                 step=5, width=640, height=480):
        super(MockDetector, self).__init__()
        self.preset_boxes = boxes
        self.class_id = class_id
        self.confidence = float(confidence)
        self.label = str(label)
        self.step = int(step)
        self.width = int(width)
        self.height = int(height)
        self._frame_count = 0

    def detect(self, frame=None):
        if frame is not None and hasattr(frame, 'shape'):
            h, w = frame.shape[:2]
        else:
            w, h = self.width, self.height

        if self.preset_boxes is not None:
            boxes = self.preset_boxes
        else:
            bw, bh = 60, 120
            max_x = max(10, w - bw - 10)
            max_y = max(10, h - bh - 10)
            x = int(50 + (self._frame_count * self.step)) % max_x
            y = int(50 + (self._frame_count * (self.step // 2 + 1))) % max_y
            boxes = [(x, y, bw, bh)]

        self._frame_count += 1
        return [
            Detection(bbox=tuple(map(int, b)),
                      class_id=self.class_id,
                      confidence=self.confidence,
                      label=self.label)
            for b in boxes
        ]

    def detect_raw_objects(self, frame, mask=None):
        detections = self.detect(frame)
        return [TailItem(bbox=d.bbox) for d in detections]

Detector.register_detector(MockDetector)


COCO_CLASSES = [
    'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat', 'traffic light',
    'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow',
    'elephant', 'bear', 'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
    'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard',
    'tennis racket', 'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
    'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
    'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard', 'cell phone',
    'microwave', 'oven', 'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear',
    'hair drier', 'toothbrush'
]


class OnnxDetector(Detector):
    """
    High-performance Edge AI Object Detector using ONNX Runtime.
    Supports YOLOv8, YOLO11, and custom ONNX detection models with zero external dependencies.
    """
    PRIORITY_PROVIDERS = [
        'CUDAExecutionProvider',
        'DmlExecutionProvider',
        'DirectMLExecutionProvider',
        'OpenVINOExecutionProvider',
        'CoreMLExecutionProvider',
        'CPUExecutionProvider'
    ]

    def __init__(self, model_path=None, conf_threshold=0.25, iou_threshold=0.45,
                 classes=None, labels=None, input_size=None, providers=None):
        super(OnnxDetector, self).__init__()
        import onnxruntime as ort

        if model_path is None:
            repo_root = os.path.abspath(os.path.join(SCRIPT_PATH, '..'))
            candidate = os.path.join(repo_root, 'models', 'yolov8n.onnx')
            if not os.path.isfile(candidate):
                try:
                    from scripts.download_models import ensure_model
                    candidate = ensure_model('yolov8n')
                except Exception:
                    pass
            model_path = candidate

        self.model_path = os.path.abspath(model_path)
        if not os.path.isfile(self.model_path):
            raise IOError("ONNX model file not found at: {}. Please run scripts/download_models.py".format(self.model_path))

        self.conf_threshold = float(conf_threshold)
        self.iou_threshold = float(iou_threshold)
        self.custom_input_size = input_size

        if labels is None:
            self.labels = {i: name for i, name in enumerate(COCO_CLASSES)}
        elif isinstance(labels, (list, tuple)):
            self.labels = {i: name for i, name in enumerate(labels)}
        elif isinstance(labels, dict):
            self.labels = labels
        else:
            raise TypeError("labels must be a list, tuple, or dict")

        if classes is not None:
            resolved_classes = set()
            for c in classes:
                if isinstance(c, int):
                    resolved_classes.add(c)
                elif isinstance(c, (str, bytes)):
                    for cid, lbl in self.labels.items():
                        if lbl.lower() == str(c).lower():
                            resolved_classes.add(cid)
            self.classes = resolved_classes
        else:
            self.classes = None

        self.providers = self.get_available_execution_providers(providers)

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(self.model_path, sess_options=opts, providers=self.providers)
        self.active_provider = self.session.get_providers()[0]

        self.input_node = self.session.get_inputs()[0]
        self.input_name = self.input_node.name
        self.output_names = [o.name for o in self.session.get_outputs()]

        self.net_h, self.net_w = self._resolve_input_size(self.input_node.shape, self.custom_input_size)

    @classmethod
    def get_available_execution_providers(cls, requested=None):
        import onnxruntime as ort
        if requested:
            if isinstance(requested, (str, bytes)):
                requested = [requested]
            return list(requested)
        available = set(ort.get_available_providers())
        providers = [p for p in cls.PRIORITY_PROVIDERS if p in available]
        return providers if providers else ['CPUExecutionProvider']

    def _resolve_input_size(self, shape, custom_input_size):
        if custom_input_size is not None:
            if isinstance(custom_input_size, (int, float)):
                return int(custom_input_size), int(custom_input_size)
            elif isinstance(custom_input_size, (tuple, list)) and len(custom_input_size) == 2:
                return int(custom_input_size[1]), int(custom_input_size[0])
        if len(shape) == 4:
            h = shape[2] if isinstance(shape[2], int) and shape[2] > 0 else 640
            w = shape[3] if isinstance(shape[3], int) and shape[3] > 0 else 640
            return h, w
        return 640, 640

    @staticmethod
    def letterbox(frame, target_shape=(640, 640), fill_value=(114, 114, 114)):
        target_h, target_w = target_shape
        orig_h, orig_w = frame.shape[:2]

        r = min(float(target_w) / float(orig_w), float(target_h) / float(orig_h))
        new_w = int(round(orig_w * r))
        new_h = int(round(orig_h * r))
        pad_x = (target_w - new_w) / 2.0
        pad_y = (target_h - new_h) / 2.0

        if (orig_w, orig_h) != (new_w, new_h):
            resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        else:
            resized = frame

        top = int(round(pad_y - 0.1))
        bottom = int(round(pad_y + 0.1))
        left = int(round(pad_x - 0.1))
        right = int(round(pad_x + 0.1))

        padded = cv2.copyMakeBorder(resized, top, bottom, left, right,
                                    cv2.BORDER_CONSTANT, value=fill_value)
        return padded, r, (pad_x, pad_y)

    @staticmethod
    def nms_numpy(boxes, scores, iou_threshold=0.45):
        if len(boxes) == 0:
            return []
        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(int(i))
            if order.size == 1:
                break
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            union = areas[i] + areas[order[1:]] - inter
            iou = np.where(union > 0, inter / np.maximum(union, 1e-6), 0.0)
            inds = np.where(iou <= iou_threshold)[0]
            order = order[inds + 1]
        return keep

    def detect(self, frame):
        if frame is None or getattr(frame, 'size', 0) == 0:
            return []

        orig_h, orig_w = frame.shape[:2]

        if len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif len(frame.shape) == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        padded, r, (pad_x, pad_y) = self.letterbox(frame, (self.net_h, self.net_w))
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        blob = rgb.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[None, ...]

        outputs = self.session.run(self.output_names, {self.input_name: blob})
        raw_pred = outputs[0]

        if raw_pred.ndim == 3:
            if raw_pred.shape[1] < raw_pred.shape[2]:
                preds = np.transpose(raw_pred[0], (1, 0))
            else:
                preds = raw_pred[0]
        elif raw_pred.ndim == 2:
            preds = raw_pred
        else:
            return []

        if preds.shape[0] == 0 or preds.shape[1] < 5:
            return []

        cx = preds[:, 0]
        cy = preds[:, 1]
        bw = preds[:, 2]
        bh = preds[:, 3]
        scores = preds[:, 4:]

        if scores.size > 0 and (scores.min() < 0.0 or scores.max() > 1.0):
            scores = 1.0 / (1.0 + np.exp(-np.clip(scores, -50.0, 50.0)))

        if scores.shape[1] == 1:
            class_ids = np.zeros(len(scores), dtype=int)
            confidences = scores[:, 0]
        else:
            class_ids = np.argmax(scores, axis=1)
            confidences = scores[np.arange(len(scores)), class_ids]

        conf_mask = confidences >= self.conf_threshold
        if not np.any(conf_mask):
            return []

        cx = cx[conf_mask]
        cy = cy[conf_mask]
        bw = bw[conf_mask]
        bh = bh[conf_mask]
        class_ids = class_ids[conf_mask]
        confidences = confidences[conf_mask]

        if self.classes is not None:
            cls_mask = np.isin(class_ids, list(self.classes))
            if not np.any(cls_mask):
                return []
            cx = cx[cls_mask]
            cy = cy[cls_mask]
            bw = bw[cls_mask]
            bh = bh[cls_mask]
            class_ids = class_ids[cls_mask]
            confidences = confidences[cls_mask]

        x1 = cx - bw / 2.0
        y1 = cy - bh / 2.0
        x2 = cx + bw / 2.0
        y2 = cy + bh / 2.0

        orig_x1 = np.clip((x1 - pad_x) / r, 0.0, float(orig_w))
        orig_y1 = np.clip((y1 - pad_y) / r, 0.0, float(orig_h))
        orig_x2 = np.clip((x2 - pad_x) / r, 0.0, float(orig_w))
        orig_y2 = np.clip((y2 - pad_y) / r, 0.0, float(orig_h))

        boxes_xyxy = np.column_stack([orig_x1, orig_y1, orig_x2, orig_y2])

        offset = class_ids[:, None].astype(float) * 4096.0
        boxes_offset = boxes_xyxy + offset
        keep = self.nms_numpy(boxes_offset, confidences, self.iou_threshold)

        detections = []
        for idx in keep:
            bx1, by1, bx2, by2 = boxes_xyxy[idx]
            w = max(1, int(round(bx2 - bx1)))
            h = max(1, int(round(by2 - by1)))
            x = int(round(bx1))
            y = int(round(by1))
            cid = int(class_ids[idx])
            conf = float(confidences[idx])
            label = self.labels.get(cid, "class_{}".format(cid))
            detections.append(Detection(bbox=(x, y, w, h), class_id=cid, confidence=conf, label=label))

        return detections

    def detect_raw_objects(self, frame, mask=None):
        detections = self.detect(frame)
        return [TailItem(bbox=d.bbox) for d in detections]

Detector.register_detector(OnnxDetector)


def _create_yolov8_detector(*args, **kwargs):
    if 'model_path' not in kwargs and len(args) == 0:
        repo_root = os.path.abspath(os.path.join(SCRIPT_PATH, '..'))
        model_path = os.path.join(repo_root, 'models', 'yolov8n.onnx')
        if not os.path.isfile(model_path):
            try:
                from scripts.download_models import ensure_model
                model_path = ensure_model('yolov8n')
            except Exception:
                pass
        kwargs['model_path'] = model_path
    return OnnxDetector(*args, **kwargs)


def _create_yolo11_detector(*args, **kwargs):
    if 'model_path' not in kwargs and len(args) == 0:
        repo_root = os.path.abspath(os.path.join(SCRIPT_PATH, '..'))
        model_path = os.path.join(repo_root, 'models', 'yolo11n.onnx')
        if not os.path.isfile(model_path):
            try:
                from scripts.download_models import ensure_model
                model_path = ensure_model('yolo11n')
            except Exception:
                pass
        kwargs['model_path'] = model_path
    return OnnxDetector(*args, **kwargs)


# Populate default factory mappings
DetectorFactory.register('yolov8', _create_yolov8_detector)
DetectorFactory.register('yolov8n', _create_yolov8_detector)
DetectorFactory.register('yolo11', _create_yolo11_detector)
DetectorFactory.register('yolo11n', _create_yolo11_detector)
DetectorFactory.register('onnx', OnnxDetector)
DetectorFactory.register('mock', MockDetector)
DetectorFactory.register('haar', HaarCascadeDetector)
DetectorFactory.register('cascade', HaarCascadeDetector)
DetectorFactory.register('haarcascade', HaarCascadeDetector)
DetectorFactory.register('haarcascadedetector', HaarCascadeDetector)
DetectorFactory.register('face', FaceDetector)
DetectorFactory.register('facedetector', FaceDetector)
DetectorFactory.register('yunet', YuNetFaceDetector)
DetectorFactory.register('face_yunet', YuNetFaceDetector)
DetectorFactory.register('yunetdetector', YuNetFaceDetector)
DetectorFactory.register('eye', EyeDetector)
DetectorFactory.register('eyedetector', EyeDetector)
DetectorFactory.register('color', ColorDetector)
DetectorFactory.register('colordetector', ColorDetector)


class EdgeTpuDetector(Detector):
    """
    Hardware-accelerated detector using Google Coral Edge TPU / TFLite runtime.
    Accelerates inference on Raspberry Pi and edge gateways via libedgetpu.
    """
    def __init__(self, model_path=None, conf_threshold=0.25, iou_threshold=0.45,
                 delegate_path="libedgetpu.so.1", use_edgetpu=True, labels=None, **kwargs):
        super(EdgeTpuDetector, self).__init__()
        self.conf_threshold = float(conf_threshold)
        self.iou_threshold = float(iou_threshold)
        self.use_edgetpu = bool(use_edgetpu)
        self.delegate_path = delegate_path
        self.model_path = model_path
        self.labels = labels or {i: name for i, name in enumerate(COCO_CLASSES)}
        self.interpreter = None
        self._init_interpreter()

    def _init_interpreter(self):
        try:
            try:
                from tflite_runtime.interpreter import Interpreter, load_delegate
            except ImportError:
                import tensorflow.lite as tflite
                Interpreter = tflite.Interpreter
                load_delegate = tflite.experimental.load_delegate
        except ImportError:
            self.interpreter = None
            return

        delegates = []
        if self.use_edgetpu:
            try:
                delegates.append(load_delegate(self.delegate_path))
            except Exception:
                pass

        if self.model_path and os.path.isfile(self.model_path):
            try:
                self.interpreter = Interpreter(model_path=self.model_path, experimental_delegates=delegates)
                self.interpreter.allocate_tensors()
            except Exception:
                self.interpreter = None

    def detect(self, frame):
        if self.interpreter is None or frame is None:
            return []
        try:
            input_details = self.interpreter.get_input_details()
            output_details = self.interpreter.get_output_details()
            h, w = input_details[0]['shape'][1:3]
            resized = cv2.resize(frame, (w, h))
            input_data = np.expand_dims(resized, axis=0)
            if input_details[0]['dtype'] == np.float32:
                input_data = (input_data.astype(np.float32) - 127.5) / 127.5
            self.interpreter.set_tensor(input_details[0]['index'], input_data)
            self.interpreter.invoke()

            boxes = self.interpreter.get_tensor(output_details[0]['index'])[0]
            classes = self.interpreter.get_tensor(output_details[1]['index'])[0]
            scores = self.interpreter.get_tensor(output_details[2]['index'])[0]
            orig_h, orig_w = frame.shape[:2]
            detections = []
            for i in range(len(scores)):
                if scores[i] >= self.conf_threshold:
                    ymin, xmin, ymax, xmax = boxes[i]
                    x = int(xmin * orig_w)
                    y = int(ymin * orig_h)
                    bw = int((xmax - xmin) * orig_w)
                    bh = int((ymax - ymin) * orig_h)
                    cid = int(classes[i])
                    label = self.labels.get(cid, "class_{}".format(cid))
                    detections.append(Detection(bbox=(x, y, bw, bh), class_id=cid, confidence=float(scores[i]), label=label))
            return detections
        except Exception:
            return []

    def detect_raw_objects(self, frame, mask=None):
        detections = self.detect(frame)
        return [TailItem(bbox=d.bbox) for d in detections]


Detector.register_detector(EdgeTpuDetector)
DetectorFactory.register('edgetpu', EdgeTpuDetector)
DetectorFactory.register('tflite', EdgeTpuDetector)



class Object(Agent):

    """
    It is any entity in the World that has its own characteristics or
    features and that can be tracked in the real world.
    """
    def __init__(self, frame, parent_detector,
                 max_tail_len=30, tracker_type='MEDIANFLOW', key_pts=None,
                 descriptors=None, **kwargs):
        super(Object, self).__init__()
        self._space_parent = parent_detector
        # private position deltas
        (self._dX, self._dY, self._dZ) = (None, None, None)
        # private object color
        self._BGR_color = None
        # private flag to recompute positions and tracked object
        self._to_recompute = True
        # unique features of object
        self.key_pts = key_pts  # key points for descriptors
        self.descriptors = descriptors  # descriptions for unique object
        # create deques
        self._direction_cover = 10  # last points to use to calculate direction
        self.tail = None  # deque containing points
        self.max_tail_len = max_tail_len  # maximum cached points in tail
        # tracker mechanism
        self.tracker_type = tracker_type
        self.tracker = None
        self._is_tracking = False
        # to delete stray objects
        self._stray_count = 0
        self._max_stray_count = 10
        self.live_forever = False  # do not let stray count to delete object
        # to detect zones where the object passes
        self._in_zones = []

        # first data
        self.add_to_tail(**kwargs)
        # update tracker
        self.update_tracker(frame)

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
    def dX(self):
        """get X position"""
        self.compute()  # if necessary update before giving answer
        return self._dX

    @property
    def dY(self):
        """get Y position"""
        self.compute()  # if necessary update before giving answer
        return self._dY

    @property
    def dZ(self):
        """get Z position"""
        self.compute()  # if necessary update before giving answer
        return self._dZ

    @property
    def tail_len(self):
        return len(self.tail)

    @property
    def max_tail_len(self):
        return self.tail.maxlen

    @max_tail_len.setter
    def max_tail_len(self, new_len):
        if not self._enough_items(new_len):
            raise ValueError("max_tail_len must be greater than {} and got "
                             "'{}'".format(self._enough_items(), new_len))

        try:
            old_len = self.tail.maxlen
        except AttributeError:
            # if tail is None force new tail operation
            old_len = new_len + 1
        if old_len != new_len:
            c_len = min([old_len, new_len])  # where tails can be merged
            cached_tail = self.tail  # old tail
            self.tail = deque(maxlen=new_len)  # new tail
            if cached_tail:  # either if None or no tail items
                for i, p in enumerate(cached_tail):
                    if i > c_len:
                        # break if either, old or new, lack
                        # the next tail items
                        break
                    # add from last tail items
                    self.tail.append(p)

    @property
    def is_tracking(self):
        return self._is_tracking

    @is_tracking.setter
    def is_tracking(self, value):
        if value and not self._is_tracking:
            # tracking again then clean path
            last = self.tail[0]
            self.tail.clear()
            self.tail.append(last)

        self._is_tracking = value

    @property
    def in_zones(self):
        return self._in_zones

    @in_zones.setter
    def in_zones(self, zones):
        # leave the new ones in zones and
        # find the ones that must be eliminated
        to_eliminate = []
        _in_zones = self._in_zones
        for oz in _in_zones:
            if oz in zones:
                zones.remove(oz)
            else:
                to_eliminate.append(oz)
        # eliminate zones that object is no more in
        for i in to_eliminate:
            _in_zones.remove(i)
            i._space_remove_child(self)
        # add new zones
        for nz in zones:
            _in_zones.append(nz)
            nz._space_add_child(self)

    @in_zones.deleter
    def in_zones(self):
        self.in_zones = []

    def _enough_items(self, no_items=None):
        """
        test whether number of tail items are enough to be covered
         and calculated by the direction attribute

        :param no_items: number of items in tail
        :return: True if no_items passes can be processed. If no_items is None
            it returns the no_items what would be considered True.
        """
        to_cover = self._direction_cover * 2
        if no_items is None:
            return to_cover
        if no_items >= to_cover:
            return True

    @property
    def position(self):
        """
        :return: last point or position
        """
        return self.tail[0].pt

    def get_BGR_color(self):
        """
        get object color assigned from Detector or randomly generated
        """
        if self._BGR_color is None:
            try:
                # inherit color from parent
                self._BGR_color = norm_range(self._space_parent.get_BGR_color())
            except AttributeError:
                self._BGR_color = norm_range(np.random.rand(3)*255)
        return self._BGR_color

    def add_to_tail(self, *args, **kwargs):
        """
        add a tail_item itself or from a contour (cnt), bounding box (bbox)
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
        # update key_points and descriptors
        if frame is not None:
            self._update_description(frame, tf)
        if mask is not None:
            self._fill_mask(mask, tf)
        return tf
    add_to_tail.__doc__ = add_to_tail.__doc__.format(TailItem._fields)

    def _update_description(self, frame, tail_item):
        return

    def _fill_mask(self, mask, tail_item):
        cv2.drawContours(mask, [tail_item.cnt], -1, 1, -1)

    def point_inside(self, point):
        """
        test whether point is inside object in last position

        :param point: point or x-coordinate, y-coordinate
        :return: True if inside or in contour, else False
        """
        return self.tail[0].point_inside(point)

    def point_near(self, point):
        """
        test whether point is near object in last position

        :param point: point or x-coordinate, y-coordinate
        :return: True if inside or in contour, else False
        """
        return self.tail[0].point_near(point)

    def cnt_intersect(self, cnt):
        """
        test whether last internal cnt from tail is intersected
        with external cnt

        :param cnt: external contour
        :return: True if contours intersect, else False
        """
        return self.tail[0].cnt_intersect(cnt)

    def cnt_near(self, cnt):
        """
        test whether last internal cnt from tail is near
        with external cnt

        :param cnt: external contour
        :return: True if contours intersect, else False
        """
        return self.tail[0].cnt_near(cnt)

    def direction(self, x_axis=("left", "right"), y_axis=("up", "down"),
                  z_axis=("far", "near")):
        """
        get tracked object direction in a readable form
        
        :param x_axis: names of the extremes in the x axis. ("left", "right")
        :param y_axis: names of the extremes in the y axis. ("up", "down")
        :param z_axis: names of the extremes in the z axis. ("far", "near")
        :return: x_axis, y_axis, z_axis directions
        """

        (dirX, dirY, dirZ) = ("", "", "")
        if not self.compute():  # if necessary update before giving answer
            # if there was no update but it needed to update
            return "-".join((dirX, dirY, dirZ))

        dX, dY, dZ = self._dX, self._dY, self._dZ
        # ensure there is significant movement in the
        # x-direction,
        if np.abs(dX) > 0:
            dirX = x_axis[1] if np.sign(dX) == 1 else x_axis[0]

        # y-direction,
        if np.abs(dY) > 0:
            dirY = y_axis[1] if np.sign(dY) == 1 else y_axis[0]

        # and z-direction
        if np.abs(dZ) > 0:
            dirZ = z_axis[1] if np.sign(dY) == 1 else z_axis[0]

        return "-".join((dirX, dirY, dirZ))

    def _compute(self):
        # check there are enough points
        tail = self.tail
        if not self._enough_items(len(tail)):
            return  # still to compute, nothing done

        cover = self._direction_cover
        # how many points to cover
        #average = np.average([np.array(tail[i]) for i in np.arange(cover)], 0)
        #rolled = np.average([np.array(tail[-i-1]) for i in np.arange(cover)], 0)
        average = (np.sum(np.array([np.array(tail[i].pt)*(cover-i)
                                   for i in xrange(cover)]), 0)
                   / np.sum(np.arange(cover) + 1))
        rolled = (np.sum(np.array([np.array(tail[-i-1].pt)*(cover-i)
                                 for i in xrange(cover)]), 0)
                / np.sum(np.arange(cover) + 1))
        # compute the difference between the x and y coordinates
        self._dX, self._dY, self._dZ = [int(i) for i in (average - rolled)]
        self._to_recompute = False  # computed

    def update_tracker(self, frame, mask=None, tracker_type=None, **kwargs):
        if tracker_type is None:
            tracker_type = self.tracker_type

        tk_name = tracker_type.upper()

        def _get_cv2_tracker(method_name):
            if hasattr(cv2, method_name):
                return getattr(cv2, method_name)()
            if hasattr(cv2, 'legacy') and hasattr(cv2.legacy, method_name):
                return getattr(cv2.legacy, method_name)()
            raise ValueError("Tracker '{}' is not available in OpenCV {}".format(method_name, getattr(cv2, '__version__', 'unknown')))

        if int(cv_major_ver) < 3:
            tracker = cv2.Tracker_create(tk_name)
        elif tk_name == 'BOOSTING':
            tracker = _get_cv2_tracker('TrackerBoosting_create')
        elif tk_name == 'MIL':
            tracker = _get_cv2_tracker('TrackerMIL_create')
        elif tk_name == 'KCF':
            tracker = _get_cv2_tracker('TrackerKCF_create')
        elif tk_name == 'TLD':
            tracker = _get_cv2_tracker('TrackerTLD_create')
        elif tk_name == 'MEDIANFLOW':
            tracker = _get_cv2_tracker('TrackerMedianFlow_create')
        elif tk_name == 'MOSSE':
            tracker = _get_cv2_tracker('TrackerMOSSE_create')
        elif tk_name == 'CSRT':
            tracker = _get_cv2_tracker('TrackerCSRT_create')
        elif tk_name == 'GOTURN':
            tracker = _get_cv2_tracker('TrackerGOTURN_create')
        else:
            raise ValueError("tracker_type '{}' not supported".format(tracker_type))

        # add tail if tracker was created
        if kwargs:
            # renewing tracker and correct it
            tf = self.add_to_tail(mask=mask, frame=frame, **kwargs)
        else:
            # renewing tracker from last item in tail
            tf = self.tail[0]

        # register new tracker if tail was added successfully
        self.tracker_type = tracker_type
        self.tracker = tracker
        self.is_tracking = tracker.init(frame, tf.bbox)

    def update(self, frame, mask=None):
        # Update tracker
        self.is_tracking, bbox = self.tracker.update(frame)
        if self.is_tracking:
            self.add_to_tail(mask=mask, frame=frame, bbox=bbox)

    def draw_circle(self, frame, color=None):
        # draw the circle and centroid on the frame,
        # then update the list of tracked points
        if color is None:
            color = self.get_BGR_color()
        else:
            color = norm_range(color)
        try:
            x, y, _ = self.position
            (_, radius) = cv2.minEnclosingCircle(self.tail[0].cnt)
            center = (int(x), int(y))
            cv2.circle(frame, center, int(radius), color, 2)
            cv2.circle(frame, center, 5, norm_range([255-i for i in color]), -1)
        except IndexError:
            pass

    def draw_tail(self, frame, color=None, iterate=None):
        """
        Draw object tail on frame

        :param frame: frame to draw on
        :param color: color of tail (1x3 array)
        :param iterate: iterate over positions
        :return:
        """
        if color is None:
            color = self.get_BGR_color()
        else:
            color = norm_range(color)
        tail = self.tail
        if iterate is None:
            iterate = xrange(1, len(tail))
        # loop over the set of tracked points
        for i in iterate:
            # if either of the tracked data are None, ignore them
            if tail[i - 1] is None or tail[i] is None:
                continue
            # otherwise, compute the thickness of the line and
            # draw the connecting lines
            thickness = int(np.sqrt(self.tail_len / float(i + 1)) * 2.5)
            cv2.line(frame, tail[i - 1].pt[:2], tail[i].pt[:2], color, thickness)

    def draw_stats(self, frame, position=None, fontFace=None, fontScale=None,
                   color=None, thickness=None, tag=None):
        """

        :param frame:
        :param position:
        :param fontFace:
        :param fontScale:
        :param color:
        :param thickness:
        :param tag:
        :return:
        """
        if position is None:
            position = (10, frame.shape[0] - 10)
        if fontFace is None:
            fontFace = cv2.FONT_HERSHEY_SIMPLEX
        if fontScale is None:
            fontScale = 0.35
        if color is None:
            color = self.get_BGR_color()
        else:
            color = norm_range(color)
        if thickness is None:
            thickness = 1
        if tag is None:
            tag = "dx: {dx}, dy: {dy}, dz: {dz} \n{direction}"
        # show the movement deltas and the direction of movement on
        # the frame
        text = tag.format(dx=self.dX, dy=self.dY, dz=self.dZ,
                          direction=self.direction())
        cv2.putText(frame, text, position, fontFace=fontFace,
                    fontScale=fontScale, color=color, thickness=thickness)

    def __json_enco__(self):
        return self.max_tail_len

    def _parent_changed_event(self, old_parent):
        return