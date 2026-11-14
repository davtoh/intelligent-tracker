#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Legacy camera capture wrappers (UnifiedCamera, MockVideoCapture, PiCamera fallback)."""

import sys
from time import sleep, time

import cv2
import numpy as np


class CameraError(Exception):
    """Raised when a legacy camera device fails to open or capture."""

    def __init__(self, *args):
        super().__init__(*args)


class MockVideoCapture:
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
        frame[:, :, 0] = (np.arange(self.height)[:, None] * 255 // self.height).astype(np.uint8)
        frame[:, :, 1] = (np.arange(self.width)[None, :] * 255 // self.width).astype(np.uint8)
        cx = int((self.width // 2) + (self.width // 4) * np.sin(self.frame_idx * 0.05))
        cy = int((self.height // 2) + (self.height // 4) * np.cos(self.frame_idx * 0.05))
        cv2.circle(frame, (cx, cy), 35, (0, 0, 255), -1)
        return True, frame

    def release(self):
        self._opened = False


def _open_camera_backend(camera_num, allow_mock: bool):
    """Probe OpenCV or mock capture backend and return (camera_obj, resolved_num)."""
    if camera_num in ("mock", "synthetic"):
        return MockVideoCapture(), camera_num

    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else 0
    if camera_num is None:
        for idx in range(5):
            cam = cv2.VideoCapture(idx, backend) if backend else cv2.VideoCapture(idx)
            if cam.isOpened():
                return cam, idx
            cam.release()
        if allow_mock:
            print("Notice: No hardware camera found. Falling back to MockVideoCapture synthetic feed.")
            return MockVideoCapture(), "mock"
        raise CameraError("no camera found")

    cam = cv2.VideoCapture(camera_num, backend) if backend else cv2.VideoCapture(camera_num)
    if not cam.isOpened() and allow_mock:
        print("Notice: Camera {} failed to open. Falling back to MockVideoCapture.".format(camera_num))
        return MockVideoCapture(), "mock"
    return cam, camera_num


class UnifiedCamera:
    """
    Emulate PiCamera in a system that does not have PiCamera support
    with a normal cv2.VideoCapture supported by OpenCV.
    """

    # https://github.com/waveform80/picamera/blob/master/picamera/camera.py
    # https://www.pyimagesearch.com/2015/03/30/accessing-the-raspberry-pi-camera-with-opencv-and-python/
    def __init__(self, camera_num=None, allow_mock=True):
        self.resolution = None
        self.framerate = None
        self._camera, self._camera_num = _open_camera_backend(camera_num, allow_mock)
        self._closed = False

    def start_preview(self):
        if not self._camera.isOpened():
            self._camera.open(self._camera_num)
        if not self._camera.isOpened():
            raise CameraError("camera {} could not be opened".format(self._camera_num))
        self._camera.read()  # activate it
        self._closed = False

    def capture(self, rawCapture, format="jpeg", use_video_port=False):
        grabbed, frame = self._camera.read()
        if not grabbed:
            return frame

        res = self.resolution
        if res is not None and frame.shape[:2] != res:
            frame = cv2.resize(frame, res)

        fmt = format.lower()
        if fmt in ("rgb", "jpeg"):
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        elif fmt in ("png", "rgba"):
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
        elif fmt == "bgra":
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
        return frame

    def capture_continuous(self, rawCapture, format="jpeg", use_video_port=False):
        diff_time = 1 / self.framerate  # second / frame per second
        timer = time() + diff_time  # do not wait in first frame
        while True:
            timer_new = time()
            elapsed = timer_new - timer
            if elapsed < diff_time:
                remain = diff_time - elapsed
                sleep(remain)
                timer_new += remain
            timer = timer_new
            yield self.capture(rawCapture, format, use_video_port)

    def close(self):
        if self._camera is not None:
            try:
                self._camera.release()
            except Exception:
                pass
        self._closed = True
        if sys.platform.startswith("win"):
            sleep(0.05)

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
    from picamera import PiCamera
    from picamera.array import PiRGBArray
except ImportError:

    class PiRGBArray:
        """
        Emulate PiRGBArray in a system that does not have PiCamera support
        with a normal camera input supported by OpenCV.
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
            self.array = np.zeros(value[:2][::-1] + (3,), np.uint8) if value is not None else None

        @size.deleter
        def size(self):
            del self._size

        def truncate(self, val=0):
            return

        def close(self):
            self.array = None

    PiCamera = UnifiedCamera  # emulates PiCamera
