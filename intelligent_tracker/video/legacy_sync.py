#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Legacy multi-camera threaded stream and synchronization wrappers."""

from numbers import Number
from threading import Event, RLock, Thread
from time import sleep, time

from intelligent_tracker.video.legacy_camera import (
    CameraError,
    PiCamera,
    PiRGBArray,
    UnifiedCamera,
)


class _ManagedStreamContext:
    """Shared context manager lifecycle for start()/close() stream wrappers."""

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def _set_sync_framerate(sync_cams, value) -> None:
    """Update target framerate for SyncCameras."""
    if value and sync_cams._framerate != value:
        sync_cams._framerate = value


def _set_sync_resolutions(sync_cams, value) -> None:
    """Apply shared or per-stream resolution tuples to SyncCameras."""
    if value:
        if isinstance(value[0], Number):
            for stream in sync_cams.streams:
                stream.resolution = value
        else:
            for stream, res in zip(sync_cams.streams, value):
                stream.resolution = res
    sync_cams._resolution = [stream.resolution for stream in sync_cams.streams]


class VideoStream(_ManagedStreamContext):
    """Threaded legacy camera stream wrapper with trigger synchronization."""

    resolution = property(
        lambda self: self.camera.resolution,
        lambda self, value: setattr(self.camera, "resolution", value),
    )
    framerate = property(
        lambda self: self.camera.framerate,
        lambda self, value: setattr(self.camera, "framerate", value),
    )

    def __init__(
        self,
        src=None,
        usePiCamera=False,
        resolution=(320, 240),
        framerate=30,
        format="bgr",
        trigger=None,
    ):
        if usePiCamera:
            self.camera = PiCamera()
        elif isinstance(src, (UnifiedCamera, PiCamera)):
            self.camera = src
        else:
            self.camera = UnifiedCamera(src)
        self.resolution = resolution
        self.framerate = framerate
        self.rawCapture = PiRGBArray(self.camera, size=resolution)
        self._warm_up_time = 2
        self._creation_time = time()

        self.frame = None
        self._stop = True
        self.trigger = trigger if trigger is not None else Event()
        self.format = format
        self._thread_free = Event()
        self._order = Event()
        self._lock = RLock()
        self._thread = None
        self._frame_cache = None
        self._optimize = True

    def _update_func(self):
        try:
            df = time() - self._creation_time
            if df < self._warm_up_time:
                sleep(self._warm_up_time - df)
            self.camera.start_preview()
            self.frame = self.camera.capture(self.rawCapture, self.format)
            if self.frame is None:
                raise CameraError("camera '{}' not working".format(self.camera))
            self._thread_free.set()
            while not self._stop:
                # Wait on shared trigger unless woken for synchronized capture.
                if self._optimize:
                    wait_sec = 1 / self.framerate if self.framerate else 10
                    self.trigger.wait(wait_sec)
                self.frame = self.camera.capture(self.rawCapture, self.format)
                self.rawCapture.truncate(0)
                if self._frame_cache is None and self.trigger.is_set():
                    self._frame_cache = self.frame
                    self._order.set()
        finally:
            self.camera.close()
            self._stop = True
            self._thread_free.set()  # prevents blocking in main
            self._order.set()  # prevents blocking in main

    def read(self):
        if self.trigger.is_set():
            self._order.wait()
            return self._frame_cache
        return self.frame

    def clear_order(self):
        self._frame_cache = None
        self._order.clear()

    def get_frame(self):
        """Safely return frame from latest read."""
        if self._stop:
            raise RuntimeError("{} must be started".format(type(self)))
        return self.read()

    def start(self):
        """Start the background capture thread."""
        with self._lock:
            if self.closed():
                self._thread = t = Thread(target=self._update_func, args=())
                t.daemon = False
                self._stop = False
                self._thread_free.clear()
                t.start()
                self._thread_free.wait(10)
                if self._stop:
                    raise CameraError("camera '{}' not ready".format(self.camera))
        return self

    def close(self):
        """Signal the capture thread to stop and join outside the lock."""
        thread = None
        with self._lock:
            if not self.closed():
                self._stop = True
                self._thread_free.clear()
                self.trigger.set()  # un-pause threads
                thread = self._thread
        if thread is not None:
            thread.join(10)
            if not self.closed():
                raise Exception("Thread didn't close")

    def closed(self):
        with self._lock:
            return self._thread is None or not self._thread.is_alive()


class SyncCameras(_ManagedStreamContext):
    """Synchronize multiple legacy VideoStream camera feeds via a shared trigger."""

    framerate = property(lambda self: self._framerate, _set_sync_framerate)
    resolutions = property(lambda self: self._resolution, _set_sync_resolutions)

    def __init__(self, cameras, resolution=None, framerate=None):
        self._framerate = 30
        self._resolution = None
        self.trigger = Event()  # http://effbot.org/zone/thread-synchronization.htm
        self.streams = [VideoStream(cam, trigger=self.trigger) for cam in cameras]
        self.resolutions = resolution
        self.framerate = framerate

    def capture(self):
        try:
            self.trigger.set()
            return [stream.read() for stream in self.streams]
        except Exception as e:
            self.close()
            raise e
        finally:
            self.trigger.clear()
            for stream in self.streams:
                stream.clear_order()

    def capture_continuous(self):
        """Continuously produce synchronized camera frame lists."""
        diff_time = 1 / self.framerate
        timer = time() + diff_time  # do not wait in first frame
        while not any(stream.closed() for stream in self.streams):
            timer_new = time()
            elapsed = timer_new - timer
            diff_time = 1 / self.framerate
            if elapsed < diff_time:
                remain = diff_time - elapsed
                sleep(remain)
                timer_new += remain
            timer = timer_new
            yield self.capture()

    def close(self):
        for stream in self.streams:
            stream.close()

    def start(self):
        try:
            for stream in self.streams:
                stream.start()
        except Exception as e:
            self.close()
            raise e

    def closed(self):
        return all(stream.closed() for stream in self.streams)

    def add_camera(self, camera):
        stream = VideoStream(camera, trigger=self.trigger)
        if not self.closed():
            stream.start()
        self.streams.append(stream)

    def remove_camera(self, stream):
        try:
            idx = self.streams.index(stream)
        except ValueError:
            for idx, existing in enumerate(self.streams):
                if existing.camera == stream:
                    break
            else:
                raise ValueError("{} is not in {}".format(stream, self))

        removed = self.streams.pop(idx)
        removed.close()

