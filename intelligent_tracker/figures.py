#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# import built-in modules
import sys

# import third party modules
from matplotlib import pyplot as plt

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


# https://stackoverflow.com/q/24921234/5288758
# fastplt(draw_contour_groups([[cnt0], [cnt1]]), interpolation="nearest")


def _onpick(event):
    """
    pick function for interactive points
    """
    scat = event.artist
    poly = scat._polyline
    pl = len(poly)
    if scat._print:
        msg = "{}".format(poly)
        if pl > 1:
            #xy = scat.get_offsets()
            msg += " exactly in {}".format(poly[event.ind])
        print(msg)
    scat._print = not scat._print

    # https://stackoverflow.com/a/32952530/5288758
    scat._facecolors[:,:3] = 1 - scat._facecolors[:,:3]
    scat._edgecolors[:,:3] = 1 - scat._edgecolors[:,:3]
    scat._sizes = scat._sizes*scat._sizes_offset
    scat._sizes_offset = 1/scat._sizes_offset
    scat.figure.canvas.draw()


def interactive_points(im, points):
    """
    create an interactive window to visualize points in image.

    :param im: image to draw points on
    :param points: list of Poly objects or points
    :return:
    """
    xpixels = im.shape[1]
    ypixels = im.shape[0]

    dpi = 72
    scalefactor = 1

    xinch = xpixels * scalefactor / dpi
    yinch = ypixels * scalefactor / dpi

    fig = plt.figure(figsize=(xinch, yinch))
    ax = plt.axes([0, 0, 1, 1], frame_on=False, xticks=[], yticks=[])
    implot = ax.imshow(im, interpolation="nearest")
    ax.autoscale(False)  # https://stackoverflow.com/a/9120929/5288758
    #plt.savefig('same_size.png', dpi=dpi)
    # use scatter as in https://stackoverflow.com/a/5073509/5288758
    for p in points:
        #x, y = list(zip(*((i, j) for ((i, j),) in (p.lines_points()))))
        #scat = ax.scatter(x, y, s=150, picker=True)
        scat = ax.scatter([], [], s=50, c="r", picker=True, marker="s")
        scat.set_offsets(list(p))
        scat._polyline = p
        scat._sizes_offset = 2
        scat._print = True
    fig.canvas.mpl_connect('pick_event', _onpick)
    fig.show()