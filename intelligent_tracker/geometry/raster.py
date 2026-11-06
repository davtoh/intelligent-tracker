"""Raster image drawing operations and binary contour intersection masks."""

from typing import Callable, List, Tuple

import cv2
import numpy as np


def draw_drawContours(img: np.ndarray, cnt: np.ndarray) -> np.ndarray:
    """Drawing function used to draw contour."""
    return cv2.drawContours(img, [cnt], -1, 1, -1)


def draw_fillConvexPoly(img: np.ndarray, cnt: np.ndarray) -> np.ndarray:
    """Draw contour into mask. For it to be correct it must be convex."""
    return cv2.fillConvexPoly(img, cnt, 1, cv2.LINE_4)


def draw_fillPoly(img: np.ndarray, cnt: np.ndarray) -> np.ndarray:
    """Drawing function used to fill complex contour polygon."""
    return cv2.fillPoly(img, [cnt], 1, cv2.LINE_4)


def intersect_AND(
    img: np.ndarray,
    contours: List[np.ndarray],
    function: Callable[[np.ndarray, np.ndarray], np.ndarray] = draw_drawContours,
) -> Tuple[List[np.ndarray], np.ndarray]:
    """Intersect contours by applying logical AND operations on raster masks.

    :param img: Initial binary image
    :param contours: Contours to overlap
    :param function: Drawing function
    :return: Final binary image, overlapped contours
    """
    blank = np.zeros(img.shape[0:2])
    for cnt in contours:
        bn = function(blank.copy(), cnt)
        img = np.logical_and(img, bn)
    return cv2.findContours(
        img.astype(np.uint8),
        mode=cv2.RETR_LIST,
        method=cv2.CHAIN_APPROX_SIMPLE,
    )[:2]


def intersect_ADD(
    img: np.ndarray,
    contours: List[np.ndarray],
    function: Callable[[np.ndarray, np.ndarray], np.ndarray] = draw_drawContours,
) -> Tuple[List[np.ndarray], np.ndarray]:
    """Intersect contours by applying ADD operations and thresholding.

    :param img: Initial binary image
    :param contours: Contours to overlap
    :param function: Drawing function
    :return: Final binary image, overlapped contours
    """
    blank = np.zeros(img.shape[0:2])
    num_cnt = len(contours)
    for cnt in contours:
        bn = function(blank.copy(), cnt)
        img += bn
    return cv2.findContours(
        (img == (num_cnt + 1)).astype(np.uint8),
        mode=cv2.RETR_LIST,
        method=cv2.CHAIN_APPROX_SIMPLE,
    )[:2]

