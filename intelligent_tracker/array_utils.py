#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# import built-in modules
import sys

# import third party modules
import cv2
import numpy as np
from numbers import Number
#from RRtoolbox.lib.arrayops import overlay

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


def is_numpy(obj):
    """
    returns True if object is obj numpy object
    """
    return type(obj).__module__ == np.__name__


def convert(points, roll=None, _type=int, shift=None, apply="contours"):
    """
    Convert contour or points.

    :param points: contours or points
    :param roll: roll points
    :param _type: convert points to type
    :param shift: shift points to (x, y)
    :param apply: apply operations the combination "contours-points-list-array"
    :return: converted points
    """

    # normalize them to array
    conv = np.array(points, _type)
    assert not len(conv) or 2 == conv[0].size

    # roll array
    if roll is not None:
        conv = np.roll(conv, roll * 2)

    # shift array
    if shift is not None:
        conv += shift

    if apply is None:
        # determine operations by inspecting data
        apply = ""
        if not is_numpy(points):
            apply += "list"
        if len(points) and is_numpy(points[0]):
            apply += "-contours"
        else:
            apply += "-points"

    if "point" in apply:
        conv = conv.reshape(-1, 2)
        if "list" in apply:
            return [tuple(i) for i in conv]
    elif "contour" in apply:
        conv = conv.reshape(-1, 1, 2)
        if "list" in apply:
            return list(conv)
    #elif "array" in apply:
    #    pass
    return conv


def norm_range(vec, lower=0, upper=255, type=int):
    """
    clips vector to range [lower, upper] and a tuple with integers

    :param vec: vector
    :param lower: 0
    :param upper: 255
    :param type: int
    :return:
    """
    newvec = []
    upper = type(upper)
    lower = type(lower)
    for i in vec:
        if i > upper:
            newvec.append(upper)
        elif i < lower:
            newvec.append(lower)
        else:
            newvec.append(type(i))
    return tuple(newvec)


def draw_contour_groups(contour_groups, shape=None, binary=False):
    """
    draw contours in separate colors

    :param contour_groups: list of contours
    :param shape: shape to draw on. If None shape is calculated.
    :param binary: True to draw with Ones, False to draw with colors.
    :return: image
    """
    if shape is None:
        # get the maximum coordinates in x, y
        max_ = np.max([np.max([np.max(contours,0) for contours in group],0)
                       for group in contour_groups],0).reshape(2)
        # calculate pad to correct small contours
        pad = 1  #max_*np.exp(-max_*0.1) + 1
        # get fitting window in all contours
        x, y = max_ + pad
        # get fitting shape
        shape = int(y), int(x)
    if binary:
        img = np.zeros(shape[:2])
    else:
        img = np.zeros(shape[:2]+(3,))
    vis = img.copy()
    for contours in contour_groups:
        if binary:
            color = 1
        else:
            color = norm_range(np.random.rand(3) * 255, lower=20)
        over = cv2.fillPoly(img.copy(), contours, color, cv2.LINE_4)
        #over = cv2.drawContours(img.copy(), contours, -1, color, 0)
        if binary:
            vis += over
        else:
            vis = overlay(vis, over, 0.3)
        #vis = cv2.addWeighted(vis, 0.5, over, 0.5, 0.0)
    return vis


def find_roll_inv(ans, expected):
    """
    roll an array until it is best matched to an expected array

    :param ans: array to roll
    :param expected: array which ans must be rolled to
    :return: best result, inversion, roll, alltrue
    """
    assert ans.shape == expected.shape
    assert ans.size == expected.size
    best = 0
    best_ans = None
    inv = False
    roll = 0
    for inv in (False, True):
        if inv:
            ans = ans[::-1]  # copy it
        for roll in range(ans.size):
            comp = np.roll(ans, roll) == expected
            ind = np.sum(comp)
            # equivalent to np.alltrue(comp)
            if comp.min() == True:
                return comp, inv, roll, True
            if ind > best:
                best_ans = comp
                best = ind
    return best_ans, inv, roll, False


def check_contours(ans, expected, ignore_shape=False):
    """
    check to contours are the same in an strict or lazy way.

    :param ans: contours to check
    :param expected: expected contours or ground truth
    :param ignore_shape: True to ignore order, shapes and check
        by approximation if ans yields similar results as expected.
        if ignore_shape is a number then it will be the threshold which
        is 0.1 when ignore_shape = True.
    :return:
    """
    if ignore_shape:
        if not isinstance(ignore_shape, Number):
            ignore_shape = 0.1
        # check that cnts are equal by comparing their moments
        if len(ans) == 0 and len(expected) == 0:
            # both are empty
            return True
        elif len(ans) == 0 or len(expected) == 0:
            # one of them is empty
            return False
        temp = draw_contour_groups([ans, expected], binary=True)
        body = (temp != 0).sum() + 0.0000001
        not_overlaped = (temp == 1).sum()
        ret = not_overlaped / body
        if ret > ignore_shape:
            return False
        # potentially risky if cnts are un ordered
        #for ans_c, exp_c in zip(ans, expected):
        #    ret = cv2.matchShapes(ans_c, exp_c, 1, 0.0)
        #    if ret > 0.01:
        #        return False
    else:
        if len(ans) != len(expected):
            return False
        for ans_c, exp_c in zip(ans, expected):
            # normalize them to points
            ans_c = np.array([i for i in convert(ans_c).reshape(-1, 2)])
            exp_c = np.array([i for i in convert(exp_c).reshape(-1, 2)])
            # if after normalization they are not the same shape
            # then they should not be equal
            if ans_c.shape != exp_c.shape:
                return False
            if not find_roll_inv(ans_c, exp_c)[3]:
                return False
    return True