#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# import built-in modules
import sys
from time import sleep

# import third party modules
import os
import matplotlib as _matplotlib
if 'MPLBACKEND' in os.environ:
    _matplotlib.use(os.environ['MPLBACKEND'])
else:
    # Legacy reference: _matplotlib.use('QT5Agg')  # FIXME not all back end working: tk is not thread safe
    for _backend in ('QtAgg', 'QT5Agg', 'TkAgg', 'Agg'):
        try:
            _matplotlib.backends.registry.backend_registry.load_backend_module(_backend)
            _matplotlib.use(_backend)
            break
        except Exception:
            continue
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from .array_utils import is_numpy

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


pause = plt.pause


def block(interval=0.1, conditions=None):
    """
    Block until the conditions are met. If there are not conditions
    blocks until all windows are closed.

    If there is an active figure it will be updated and displayed,
    and the GUI event loop will run during the pause.

    :param interval: interval to check conditions
    :param conditions: list of functions returning True or False
    :return:
    """
    if conditions is None:
        while True:
            pause(interval)
    else:
        while any((not i() for i in conditions)):
            pause(interval)


class EventFigure:
    """
    fig, ax = plt.subplots(FigureClass=MyFigure)
    """

    def __init__(self, img=None, title=None, interval=None, func=None,
                 frames=None, fargs=None, blit=None, **kwargs):
        # super(MyFigure, self).__init__(**kwargs)
        self._closed = None
        self._min_interval = 33  # 30 frame per second
        self._interval = None
        self.interval = interval  # apply interval limits
        self._func = func
        self._frames = frames
        self._fargs = fargs
        self._blit = blit
        self._title = title
        self.figure = plt.figure(num=title, **kwargs)
        self.ax = self.figure.add_axes([0, 0, 1, 1], frame_on=False, xticks=[], yticks=[])
        self.artist = self.ax.imshow(img, animated=bool(blit), interpolation="nearest")
        self.animation = None

    @property
    def title(self):
        return self._title

    @title.setter
    def title(self, value):
        # https://stackoverflow.com/a/5812982/5288758
        self.figure.canvas.set_window_title(value)
        self._title = value

    @title.deleter
    def title(self):
        del self._title

    @property
    def interval(self):
        return self._interval

    @interval.setter
    def interval(self, value):
        if value is not None and value < self._min_interval:
            value = self._min_interval
        self._interval = value
        try:
            self.animation._interval = value
            self.animation.event_source.interval = value
        except AttributeError:
            pass

    def _update_func(self, *args):
        # print("setting set")
        if self._interval:
            if self._frames:
                self.artist.set_array(args[0])
            res = self.update_func(*args)
            if res is not None:
                if is_numpy(res):
                    self.artist.set_data(res)
                else:
                    return res
        if self._blit:
            return self.artist,
        else:
            self.figure.canvas.draw_idle()

    def update_func(self, *args):
        return

    def key_press_event(self, event):
        return

    def update(self, img, interval=0.1):
        self.artist.set_data(img)
        #self.artist.set_array(img)
        self.figure.canvas.draw()
        self.figure.show()
        self.figure.canvas.start_event_loop(interval)

    def pause(self, interval):
        self.figure.canvas.start_event_loop(interval)

    def show(self):
        if self._closed:
            dummy = plt.figure(num=self.title)
            new_manager = dummy.canvas.manager
            new_manager.canvas.figure = self.figure
            self.figure.set_canvas(new_manager.canvas)

        #self.figure.show()
        if self._closed is None or self._closed:
            self.start_event(None)  # run start event
            
            # run at first or when creating new images
            # https://matplotlib.org/examples/event_handling/keypress_demo.html
            self.figure.canvas.mpl_connect('key_press_event',
                                           self.key_press_event)
            # https://matplotlib.org/examples/event_handling/close_event.html
            self.figure.canvas.mpl_connect('close_event', self._close_event)
            
            if self._interval or self._frames or self._func:
                try:
                    _blit_cache = self.animation._blit_cache
                except AttributeError:
                    _blit_cache = None
                try:
                    _save_seq = self.animation._save_seq
                except AttributeError:
                    _save_seq = None

                kw = dict(frames=self._frames,
                          interval=self._interval, fargs=self._fargs,
                          blit=self._blit)
                kw = {k:v for k,v in kw.items() if v is not None}

                if self._func is None:
                    func = self._update_func
                else:
                    func = self._func

                self.animation = animation.FuncAnimation(self.figure, func=func, save_count=1, **kw)

                if _blit_cache:
                    # BUG?　https://stackoverflow.com/a/41543986/5288758
                    # implement https://stackoverflow.com/a/36587952/5288758
                    self.animation._blit_cache = _blit_cache
                if _save_seq:
                    self.animation._save_seq = _save_seq

                # test function is working
                #self.animation._func()

        self.figure.show()
        if self.animation is not None:
            self.figure.canvas.draw()  # make the animation start
            #self.animation._start()
        self._closed = False

    def close(self):
        # this closes the window
        # to recover figures when closed use
        # https://stackoverflow.com/a/31731945/5288758
        plt.close(self.figure)

    def _close_event(self, event):
        self.close_event(event)
        self._closed = True

    def close_event(self, event):
        return 

    def start_event(self, event):
        return 

    def closed(self):
        return self._closed
    
    def __enter__(self):
        self.show()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
