#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# import built-in modules
import sys
from numbers import Number
from time import time

# import third party modules
#from RRtoolbox.lib.plotter import fastplt  # DEBUG
from .core import Space, Group, Agent
from .periferials import UnifiedCamera, SyncCameras, PiCamera
from .detectors import Detector
import numpy as np
from threading import Thread, RLock, Event
from .forms import EventFigure, pause
import cv2

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


class World(Space):
    """
    This is the world, here everything must be contained.
    """
    def __init__(self):
        self.scenes = Group(_space_parent=self, name="scenes")
        self.detectors = Group(_space_parent=self, name="detectors")
        
    def _apply_func(self, func_name, names=None, **kwargs):
        """
        generic function to use from all the scenes
        
        :param func_name: generic function in the scenes
        :param names: specific scenes
        :param kwargs: arguments to pass
        :return: 
        """
        if names is None:
            for i in self.scenes:
                getattr(i, func_name)(**kwargs)
        elif isinstance(names, str):
            getattr(self.scenes[names], func_name)(**kwargs)
        else:
            for name in names:
                getattr(self.scenes[name], func_name)(**kwargs)

    def show(self, *args, **kwargs):
        self._apply_func("show", *args, **kwargs)
    show.__doc__ = _apply_func.__doc__.replace("generic","show")

    def block(self, names=None, window=True, close=True):
        """
        block until scenes are closed

        :param names: specific scene names or they themselves.
        :param window: True to block until windows are closed.
            False to block until scenes are totally closed.
        :param close: True to close totally scenes once unblocked.
        :return:
        """
        if names is None:
            scenes = self.scenes
        elif isinstance(names, str):
            scenes = [self.scenes[names]]
        else:
            # only those scenes in world
            scenes = [self.scenes[i] for i in names]

        if window:
            # only leave if all scenes windows are closed
            conditions = [i.closed_window for i in scenes]
        else:
            # only leave if all scenes processes are closed
            conditions = [i.closed for i in scenes]

        try:
            while any((not i() for i in conditions)):
                pause(0.1)  # check every 0.1 seconds
        except KeyboardInterrupt:
            print("\n[INFO] Interrupt signal received (Ctrl+C). Closing scenes...")
        except Exception:
            pass

        # close all specified scenes
        if close:
            for i in scenes:
                i.close()

    def close(self, *args, **kwargs):
        self._apply_func("close", *args, **kwargs)
    close.__doc__ = _apply_func.__doc__.replace("generic","close")

    def compute(self, *args, **kwargs):
        self._apply_func("compute", *args, **kwargs)
    compute.__doc__ = _apply_func.__doc__.replace("generic","compute")

    def create_scene(self, *args, **kwargs):
        """
        create a scene in the world
        
        :param args: argument to pass to the scene
        :param kwargs: keyword arguments to past to the scene
        :return: scene
        """
        scene = Scene(*args, **kwargs)
        self.scenes.add_as_child(scene)
        return scene

    def create_detector(self, detector_type, *args, **kwargs):
        """
        create detector and assign it to the scenes
        
        :param detector_type: registered detector
        :param args: argument to pass to the detector
        :param kwargs: keyword arguments to past to the detector
        :param scenes: keyword argument specifying the scenes where the 
            detector is assigned. if None it is assigned to all the scenes.
            If False it is not assigned to any particular scene.
        :return: detector
        """
        scenes = kwargs.pop("scenes", None)
        if scenes is None:
            # assign all the available scenes
            scenes = self.scenes
        elif isinstance(scenes, (Scene, str)):
            # test scene is in scenes
            scenes = [self.scenes[scenes]]
        elif scenes is False:
            # specifically tells to not assign detector
            scenes = []
        else:
            scenes = [self.scenes[i] for i in scenes]
        
        detector = Detector.get_detector(detector_type)(*args, **kwargs)
        self.detectors.add_as_child(detector)
        self.assign_detector_to_scenes(detector, scenes)
        return detector

    def assign_detector_to_scenes(self, detector, scenes):
        """
        add a detector to the scenes
        
        :param detector: 
        :param scenes: a scene or list of scenes, either by object or name
        :return: 
        """
        try:
            for i in scenes:
                self.scenes[i].add_detector(
                    self.detectors[detector])
        except TypeError:
            self.scenes[scenes].add_detector(self.detectors[detector])

    def objects(self, detector_name=None, object_name=None):
        """
        iterate over objects in all the detectors
        
        :param detector_name: 
        :param object_name: 
        :return: 
        """
        if detector_name is not None and object_name is not None:
            yield self.detectors[detector_name].objects[object_name]
        elif detector_name is None:
            if object_name is None:
                for detector in self.detectors:
                    for obj in detector.objects:
                        yield obj
            else:
                for detector in self.detectors:
                    try:
                        yield detector.objects[object_name]
                        break
                    except KeyError:
                        continue
                else:
                    raise KeyError("object {} not found".format(object_name))
        else:
            for obj in self.detectors[detector_name].objects:
                yield obj

    def __json_enco__(self):
        pass


class Scene(Space):
    """
    This is a scene, specifically made to name places in the world
    and configure how the place is seen through the perspectives it can
    observe in places (cameras)
    
    .. code-block:: python
        
        # create a scene with two available cameras
        scene = Scene([None, None])
        # show the scene
        scene.show()
        # change resolution in shown scene
        scene.resolution = (300,200)
        # change frame rate in show scene and processing
        scene.framerate = 5
        # close and stop scene processing
        scene.close()
        # re-open scene visualization and continue processing
        scene.show()

    """
    def __init__(self, camera_ids=None, resolution=None, framerate=None,
                 calibration_cubes=None):
        """
        
        :param camera_ids: 
        :param resolution: 
        :param framerate: 
        :param calibration_cubes:
        """
        self.view = None

        try:
            camera_ids = list(camera_ids)
        except TypeError:
            camera_ids = [camera_ids]

        cameras = []
        for i in camera_ids:
            try:
                if isinstance(i, (UnifiedCamera, PiCamera)):
                    camera = i
                else:
                    camera = UnifiedCamera(i)
                cameras.append(camera)
            except IOError:
                for c in cameras:
                    c.close()
                raise 
        self.sync_stream = SyncCameras(cameras)
        self.resolution = resolution
        self.framerate = framerate
        self.calibration_cubes = calibration_cubes
        self.mask = None
        self.areas = Group(_space_parent=self, name="areas")
        self.detectors = Group(_space_parent=self, name="detectors")
        self.objects = Group(_space_parent=self, name="objects")
        self._stop = True
        self._computed_vis = None
        self._thread = None
        self._lock = RLock()
        self._thread_free = Event()
    
    def add_detector(self, detector):
        self.detectors.add_as_contained(detector)

    def get_objects_from_coor(self, x, y):
        pass

    def get_zones_from_coor(self, x, y):
        return []
    
    @property
    def active(self):
        return not self._stop

    @active.setter
    def active(self, value):
        stopped = not value
        if stopped:
            self._stop = stopped
        else:
            self.start()

    @property
    def framerate(self):
        return self.sync_stream._framerate

    @framerate.setter
    def framerate(self, value):
        self.sync_stream.framerate = value
        if value is not None and self.view is not None:
            self.view.interval = 1000//value

    @property
    def resolution(self):
        return self.sync_stream.resolutions

    @resolution.setter
    def resolution(self, value):
        self.sync_stream.resolutions = value

    def computed_vis(self):
        """
        camera feed with processed objects
        """
        vis = self._computed_vis
        if vis is None:
            return self.compute()
        return vis

    def raw_vis(self):
        """
        camera feed
        """
        if self._stop:
            # start stream for a short period
            with self.sync_stream:
                return self._apply_cube(self.sync_stream.capture())
        else:
            self.sync_stream.start()  # ensure it is started
            try:
                return self._apply_cube(self.sync_stream.capture())
            except Exception:
                self.close()
                raise

    def _apply_cube(self, captures, convert_func=None):
        if convert_func:
            return np.hstack([convert_func(c) for c in captures])
        else:
            return np.hstack(captures)

    def _name_changed_event(self, old_name):
        if self.view is not None:
            self.view.title = self.name

    def show(self, start=True, throw=True):
        """
        creates a window to visualize the scene
        """
        # start processing
        if start:
            self.start(throw=throw)

        # create view if None
        if self.view is None:

            class View(EventFigure):
                def update_func(selfo, *args):
                    # _computed_vis is the computed visualization 
                    # at any given frame and if it is None it will
                    # not update the animation in the window
                    if self._computed_vis is not None:
                        return cv2.cvtColor(self._computed_vis, cv2.COLOR_BGR2RGB)
                    return None

                def key_press_event(selfo, event):
                    if event.key == 'q':
                        selfo.close()
                    if event.key == 'd':
                        self.objects.clear_in_space()
                        #for d in self.detectors:
                        #    d.objects.clear()

            # interval can be any value but if it is 0 it is stopped
            # the refreshing of the window is determined by the self.framerate
            vis = cv2.cvtColor(self.computed_vis(), cv2.COLOR_BGR2RGB)
            self.view = View(vis, interval=1000//self.framerate,
                             blit=False, title=self.name)

        self._computed_vis.astype(np.uint8)  # test vis
        # show window
        self.view.show()
        return self.view

    def compute(self, frame=None):
        # process image to follow and detect objects in scene
        if frame is None:
            frame = self.raw_vis()
        self.mask = np.zeros(frame.shape[:2])
        # process frame
        frame_processed = frame.copy()

        # tracks all the objects on a unspoiled frame
        for d in self.detectors:
            objs = d._compute_objects(frame, self.mask, _debug_good=frame_processed,
                               _debug_bad=None)
            # add new object to the scene objects' group
            self.objects.update(objs, as_contained=True)
            # draws all the tails on the frame
            for o in d.tracked_objects():
                o.in_zones = self.get_zones_from_coor(*o.position[:2])
                if not self.closed_window() and o.visible:
                    o.draw_circle(frame_processed)
                    o.draw_tail(frame_processed)

        self._computed_vis = frame_processed
        return frame_processed

    def _update_func(self):
        #print("thread {} started".format(self._thread))
        # start streaming and computing
        try:
            with self.sync_stream:
                to_iter = self.sync_stream.capture_continuous()
                # first iteration to test it is working
                self.compute(self._apply_cube(next(to_iter)))
                # thread is ready
                self._thread_free.set()
                # keep on
                for images in to_iter:
                    self.compute(self._apply_cube(images))
                    if self._stop:
                        break
        finally:
            self._stop = True
            self._thread_free.set()
            #print("thread {} ended".format(self._thread))

    def start(self, throw=True):
        # start the thread to read frames from the video stream
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = t = Thread(target=self._update_func, args=())
                t.daemon = False
                self._stop = False  # thread started
                self._thread_free.clear()
                t.start()
                self._thread_free.wait()
                if self._stop and throw:
                    raise Exception("scene '{}' did not start".format(self))
        return self

    def close(self, window=True):
        with self._lock:
            if window:
                self.close_window()
            else:
                self._last_frame = self._computed_vis
            if self._thread is not None and self._thread.is_alive():
                self._stop = True
                self._thread.join(10)  # this can block forever
                if self._thread.is_alive():
                    raise Exception("Thread didn't close")

    def close_window(self):
        if self.view:
            self.view.close()

    def closed(self):
        with self._lock:
            return self._thread is None or not self._thread.is_alive()
    
    def closed_window(self):
        if self.view:
            return self.view.closed()
        return True  # if there is not view the it is closed

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        
    def __json_enco__(self):
        pass


class Area(Agent):
    """
    An Area is an specific region of a Scene e.g. two doors (the areas)
    can be in a store (the scene). In the real world, an Area can
    be among several Scenes but for implementation simplicity every
    Area must only be inside an specific Scene. The Area can tell when
    an object is inside it or outside.
    """
    def __init__(self, polygon, name=None, dwell_threshold=5.0, color=(0, 200, 100), **kwargs):
        super(Area, self).__init__(name=name, **kwargs)
        from intelligent_tracker.geometry import ZoneROI
        self.roi = ZoneROI(polygon=polygon, name=self.name, dwell_threshold=dwell_threshold, color=color)

    def contains(self, point):
        return self.roi.contains_point(point)

    def update(self, tracks, timestamp=None):
        return self.roi.update(tracks, timestamp=timestamp)

    @property
    def occupancy(self):
        return self.roi.occupancy

    def draw(self, frame, alpha=0.25):
        return self.roi.draw(frame, alpha=alpha)


class Line(Agent):
    """
    A line is a special kind of Area but that cannot have objects inside,
    it just tells when an object passes from one side to the other.
    """
    def __init__(self, line_segment, name=None, bidirectional=True, color=(0, 255, 255), **kwargs):
        super(Line, self).__init__(name=name, **kwargs)
        from intelligent_tracker.geometry import Tripwire
        self.tripwire = Tripwire(line_segment=line_segment, name=self.name, bidirectional=bidirectional, color=color)

    def check_crossing(self, track_id, prev_centroid, curr_centroid, timestamp=None):
        return self.tripwire.check_crossing(track_id, prev_centroid, curr_centroid, timestamp=timestamp)

    @property
    def total_in(self):
        return self.tripwire.total_in

    @property
    def total_out(self):
        return self.tripwire.total_out

    def draw(self, frame, thickness=2, show_counts=True):
        return self.tripwire.draw(frame, thickness=thickness, show_counts=show_counts)

