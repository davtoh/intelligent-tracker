#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# compatibility with python 2 and 3
from __future__ import division
from __future__ import print_function
from __future__ import absolute_import
from builtins import object

# import build-in modules
import sys

# import third party modules
import cv2
from time import time, sleep
from threading import Thread, Event, RLock
from collections import Counter
from numbers import Number

# special variables
# __all__ = []
__author__ = "David Toro"
# __copyright__ = "Copyright 2017, The <name> Project"
# __credits__ = [""]
__license__ = "GPL"
# __version__ = "1.0.0"
__maintainer__ = "David Toro"
__email__ = "davsamirtor@gmail.com"
# __status__ = "Pre-release"


class CameraError(Exception):
    pass


class MockVideoCapture(object):
    """Synthetic VideoCapture fallback for headless environments or devices without webcam."""
    def __init__(self, width=640, height=480):
        self.width = width
        self.height = height
        self._opened = True
        self.frame_idx = 0

    def isOpened(self):
        return self._opened

    def open(self, *args):
        self._opened = True
        return True

    def read(self):
        if not self._opened:
            return False, None
        self.frame_idx += 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        # Background gradient
        frame[:, :, 0] = (np.arange(self.height)[:, None] * 255 // self.height).astype(np.uint8)
        frame[:, :, 1] = (np.arange(self.width)[None, :] * 255 // self.width).astype(np.uint8)
        # Moving synthetic target
        cx = int((self.width // 2) + (self.width // 4) * np.sin(self.frame_idx * 0.05))
        cy = int((self.height // 2) + (self.height // 4) * np.cos(self.frame_idx * 0.05))
        cv2.circle(frame, (cx, cy), 35, (0, 0, 255), -1)
        return True, frame

    def release(self):
        self._opened = False


class UnifiedCamera(object):
    """
    Emulate PiCamera in a system that does not have PiCamera support
    with a normal cv2.VideoCapture supported by OpenCV
    """
    # https://github.com/waveform80/picamera/blob/master/picamera/camera.py
    # https://www.pyimagesearch.com/2015/03/30/accessing-the-raspberry-pi-camera-with-opencv-and-python/
    def __init__(self, camera_num=None, allow_mock=True):
        self.resolution = None
        self.framerate = None
        _camera = None
        if camera_num in ("mock", "synthetic"):
            _camera = MockVideoCapture()
        elif camera_num is None:
            for idx in range(5):
                _cam = cv2.VideoCapture(idx)
                if _cam.isOpened():
                    _camera = _cam
                    camera_num = idx
                    break
                _cam.release()
            if _camera is None:
                if allow_mock:
                    print("Notice: No hardware camera found. Falling back to MockVideoCapture synthetic feed.")
                    _camera = MockVideoCapture()
                    camera_num = "mock"
                else:
                    raise CameraError("no camera found")
        else:
            _camera = cv2.VideoCapture(camera_num)
            if not _camera.isOpened() and allow_mock:
                print("Notice: Camera {} failed to open. Falling back to MockVideoCapture.".format(camera_num))
                _camera = MockVideoCapture()
                camera_num = "mock"

        self._camera_num = camera_num
        self._camera = _camera
        self._closed = False

    def start_preview(self):
        if not self._camera.isOpened():
            self._camera.open(self._camera_num)
        if not self._camera.isOpened():
            raise CameraError("camera {} could not be opened".format(self._camera_num))
        self._camera.read()  # activate it
        self._closed = False

    def capture(self, rawCapture, format="jpeg",
                           use_video_port=False):
        (grabbed, frame) = self._camera.read()

        if not grabbed:
            return frame

        res = self.resolution
        if res is not None and frame.shape[:2] != res:
            frame = cv2.resize(frame, res)

        format = format.lower()
        if format in ('rgb', 'jpeg'):
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        elif format == ('png', 'rgba'):
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
        elif format == 'bgra':
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)

        #rawCapture.array[:] = frame
        return frame

    def capture_continuous(self, rawCapture, format="jpeg",
                           use_video_port=False):

        #if self.resolution is None:
        #    self.resolution = rawCapture.shape[:2]

        diff_time = 1/self.framerate  # second / frame per second
        timer = time() + diff_time  # do not wait in first frame
        while True:
            timer_new = time()
            elapsed = (timer_new - timer)
            if elapsed < diff_time:
                remain = diff_time-elapsed
                sleep(remain)
                timer_new += remain  # timer_new = time()
            timer = timer_new

            yield self.capture(rawCapture, format, use_video_port)

    def close(self):
        self._camera.release()
        self._closed = True

    def closed(self):
        return self._closed

    def __enter__(self):
        self.start_preview()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __str__(self):
        return "{}:{}".format(type(self), self._camera_num)

try:
    from picamera.array import PiRGBArray
    from picamera import PiCamera
except ImportError:
    import numpy as np

    class PiRGBArray(object):
        """
        Emulate PiRGBArray in a system that does not have PiCamera support
        with a normal camera input supported by OpenCV
        """
        def __init__(self, camera, size=None):
            self.array = None
            self.camera = camera
            self.size = size

        @property
        def size(self):
            return self._size

        @size.setter
        def size(self, value):
            self._size = value
            self.array = np.zeros(value[:2][::-1] + (3,), np.uint8)

        @size.deleter
        def size(self):
            del self._size

        def truncate(self, val=0):
            #self.array[:] = val
            return

        def close(self):
            self.array = None

    PiCamera = UnifiedCamera  # emulates PiCamera


class VideoStream(object):

    def __init__(self, src=None, usePiCamera=False, resolution=(320, 240),
                 framerate=30, format='bgr', trigger=None):
        # initialize the camera and stream
        if usePiCamera:
            self.camera = PiCamera()
        else:
            if isinstance(src, (UnifiedCamera, PiCamera)):
                self.camera = src
            else:
                self.camera = UnifiedCamera(src)
        self.resolution = resolution
        self.framerate = framerate
        self.rawCapture = PiRGBArray(self.camera, size=resolution)
        self._warm_up_time = 2
        self._creation_time = time()

        # initialize the frame and the variable used to indicate
        # if the thread should be stopped
        self.frame = None
        self._stop = True  # thread is stopped or non existent
        if trigger is None:
            trigger = Event()
        self.trigger = trigger
        self.format = format
        self._thread_free = Event()
        self._order = Event()
        self._lock = RLock()
        self._thread = None
        self._frame_cache = None
        # the optimization flag lets the camera wait until it is needed
        self._optimize = True

    @property
    def resolution(self):
        return self.camera.resolution

    @resolution.setter
    def resolution(self, value):
        self.camera.resolution = value

    @property
    def framerate(self):
        return self.camera.framerate

    @framerate.setter
    def framerate(self, value):
        self.camera.framerate = value

    def _update_func(self):
        #print("camera thread {} started".format(self._thread))
        # initialize events
        #toggle = True
        try:
            df = time() - self._creation_time
            if df < self._warm_up_time:
                # allow to warm up if camera is opened too quickly
                sleep(self._warm_up_time-df)
            self.camera.start_preview()  # start camera
            self.frame = self.camera.capture(self.rawCapture, self.format)
            if self.frame is None:
                raise CameraError("camera '{}' not working".format(self.camera))
            self._thread_free.set()  # notify thread is free to receive orders
            # keep looping infinitely until the thread is stopped
            while not self._stop:
                # because self.trigger can be shared it is possible that
                # self.read function was called setting self.trigger once
                # but this can be turned off while in other threads so
                # we have to check self.thread_free is not set meaning
                # that it has to produce a frame, thus it should not
                # be blocked
                if self._optimize:
                #    self.trigger.clear()  # make the thread wait until event
                #    #self.__debug("event waiting in {}'s thread".format(id(self)))
                    if self.framerate:
                        self.trigger.wait(1/self.framerate)  # wait until read function or event calls
                    else:
                        self.trigger.wait(10)
                #    self._thread_free.clear()  # tell thread is busy
                #    #self.__debug("event was unblocked in {}'s thread".format(id(self)))
                #    self._order.set()  # there is an order

                # if the thread indicator variable is set, stop the thread
                # and resource camera resources
                #if self._stop:
                #    break

                self.frame = self.camera.capture(self.rawCapture, self.format)
                #print("{}taking photo in {}".format((""," ")[toggle],id(self)))
                #toggle = not toggle
                # notify frame was produced and thread is free
                # as quickly as possible
                #self._thread_free.set()
                self.rawCapture.truncate(0)
                if self._frame_cache is None and self.trigger.is_set():
                    self._frame_cache = self.frame
                    self._order.set()
        finally:
            # ending thread
            #self.rawCapture.close()
            self.camera.close()
            self._stop = True
            self._thread_free.set()  # prevents blocking in main
            self._order.set()  # prent blocking in main
            #print("camera thread {} ended".format(self._thread))

    def read(self):
        if self.trigger.is_set():
            self._order.wait()
            return self._frame_cache
        return self.frame

    def clear_order(self):
        self._frame_cache = None
        self._order.clear()

    def get_frame(self):
        """
        safely give frame from latest read
        """
        if self._stop:
            raise RuntimeError("{} must be started".format(type(self)))
        return self.read()

    def start(self):
        # start the thread to read frames from the video stream
        with self._lock:
            # if several threads are trying to start it wait
            # if while this lock was waiting and this thread ended in another
            # lock, open the tread again to prevent inconsistencies
            if self.closed():
                self._thread = t = Thread(target=self._update_func, args=())
                t.daemon = False
                self._stop = False  # thread started
                self._thread_free.clear()
                t.start()
                self._thread_free.wait(10)
                if self._stop:
                    raise CameraError("camera '{}' not ready".format(self.camera))
        return self

    def close(self):
        with self._lock:
            if not self.closed():
                # indicate that the thread should be stopped
                self._stop = True
                self._thread_free.clear()
                self.trigger.set()  # un-pause threads
                self._thread.join(10)
                if not self.closed():
                    raise Exception("Thread didn't close")

    def closed(self):
        with self._lock:
            return self._thread is None or not self._thread.is_alive()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @classmethod
    def __debug(cls, data=None, start_debug=False):
        if not hasattr(cls, "checks"):
            cls.checks = Counter()
            cls.check_cum = set()

        if start_debug and data in cls.check_cum:
            cls.checks[frozenset(cls.check_cum)] += 1
            cls.check_cum = set()
            cls.check_cum.add(data)
        else:
            cls.check_cum.add(data)


class SyncCameras(object):
    """
    Synchronize cameras
    """
    def __init__(self, cameras, resolution=None, framerate=None):
        self._framerate = 30
        self._resolution = None
        self.trigger = Event()  # http://effbot.org/zone/thread-synchronization.htm
        self.streams = []
        for i in cameras:
            s = VideoStream(i, trigger=self.trigger)
            self.streams.append(s)
        self.resolutions = resolution
        self.framerate = framerate

    @property
    def framerate(self):
        return self._framerate

    @framerate.setter
    def framerate(self, value):
        if value and self._framerate != value:
            self._framerate = value

    @property
    def resolutions(self):
        return self._resolution

    @resolutions.setter
    def resolutions(self, value):
        if value:
            if isinstance(value[0], Number):
                # case resolution for all cameras
                # format: (width, high)
                for i in self.streams:
                    i.resolution = value
            else:
                # case resolution for each camera
                # format: [(width, high) ... (width, high)]
                for i, value in zip(self.streams, value):
                    i.resolution = value
        
        # get resolutions
        self._resolution = [i.resolution for i in self.streams]

    def capture(self):
        try:
            self.trigger.set()
            # give latest images from trigger
            return [i.read() for i in self.streams]
        except Exception as e:
            self.close()
            raise e
        finally:
            self.trigger.clear()  # clear trigger
            for i in self.streams:
                i.clear_order()  # clear latest images from trigger

    def capture_continuous(self):
        """
        continuously produce camera feeds
        """
        diff_time = 1/self.framerate  # second / frame per second
        timer = time() + diff_time  # do not wait in first frame
        while not any(i.closed() for i in self.streams):
            timer_new = time()
            elapsed = (timer_new - timer)
            diff_time = 1 / self.framerate  # allow to change
            if elapsed < diff_time:
                remain = diff_time-elapsed
                sleep(remain)
                timer_new += remain  # timer_new = time()
            #print("sync at {}".format(timer_new - timer))
            timer = timer_new
            yield self.capture()
    
    def close(self):
        for i in self.streams:
            i.close()

    def start(self):
        try:
            for i in self.streams:
                i.start()
        except Exception as e:
            self.close()
            raise e

    def closed(self):
        return all(i.closed() for i in self.streams)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def add_camera(self, camera):
        s = VideoStream(camera, trigger=self.trigger)
        if not self.closed():
            s.start()
        self.streams.append(s)

    def remove_camera(self, stream):
        try:
            i = self.streams.index(stream)
        except ValueError:
            # stream is camera here
            for i, j in enumerate(self.streams):
                if j.camera == stream:
                    break
            else:
                raise ValueError("{} is not in {}".format(stream, self))

        s = self.streams.pop(i)
        s.close()