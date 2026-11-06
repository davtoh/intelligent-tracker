"""Contour intersection algorithms, Sutherland-Hodgman clipping, and analytical solvers."""

from itertools import chain
from typing import List, Optional, Tuple

import numpy as np

from intelligent_tracker.geometry.associations import Completeness
from intelligent_tracker.geometry.polygons import Interception, PolyLine
from intelligent_tracker.geometry.primitives import (
    IncompleteAssociations,
    cnt_group,
    line_intersection,
    norm_point,
)


class EspList(list):
    """Special list to save statistics."""
    pass


def cnt_check_intersection(cnt0, cnt1):
    """Check if normal cnt0 and cnt1 intersect."""
    # -1 = outside, 0 = boundary, 1 = inside
    flags0, trans0_raw, found = cnt_group(cnt0, cnt1, True)
    if found:
        return found
    flags1, trans1_raw, found = cnt_group(cnt1, cnt0, True)
    if found:
        return found

    # pair variables to choose with id
    trans_raw = trans0_raw, trans1_raw
    cnts = cnt0, cnt1
    flags = flags0, flags1

    # select id as first contour that must have transitions
    id = 1 if trans1_raw else 0

    # selected variables with id
    id0, id1 = int(id), int(not id)
    id0_c, id1_c = cnts[id0], cnts[id1]
    id0_f, id1_f = flags[id0], flags[id1]

    # check
    if np.all(id0_f == -1):
        id0_trans_raw = np.arange(len(id0_f))
    else:
        id0_trans_raw = trans_raw[id0]

    if np.all(id1_f == -1):
        id1_trans_raw = np.arange(len(id1_f))
    else:
        id1_trans_raw = trans_raw[id1]

    # test connections
    for tr0 in id0_trans_raw:
        id0_i0, id0_i1 = tr0, ((tr0 - 1) % len(id0_f))
        for tr1 in id1_trans_raw:
            id1_i0, id1_i1 = tr1, ((tr1 - 1) % len(id1_f))

            l0a, l0b = id0_c[id0_i0], id0_c[id0_i1]
            l0 = norm_point(l0a), norm_point(l0b)

            l1a, l1b = id1_c[id1_i0], id1_c[id1_i1]
            l1 = norm_point(l1a), norm_point(l1b)

            if line_intersection(l0, l1, check_inside=True) is not None:
                return True
    return False


def _find_initial_interceptions(
    id0_trans_raw, id1_trans_raw, id0_f, id1_f, id0_c, id1_c, id0_t, id1_t,
    id0, id1, all_outside0, all_outside1, default_shape, conns, used_combinations
):
    """Find initial line boundary interceptions and correct raw transitions."""
    for i0, tr0 in enumerate(id0_trans_raw):
        id0_i0, id0_i1 = tr0, ((tr0 - 1) % len(id0_f))
        if all_outside0:
            tr0_correct = i0
        else:
            if id0_f[tr0] != -1:
                tr0_correct = tr0
            elif id0_f[tr0 - 1] != -1:
                tr0_correct = id0_i1
            else:
                tr0_correct = tr0
            id0_t.append(tr0_correct)

        for i1, tr1 in enumerate(id1_trans_raw):
            id1_i0, id1_i1 = tr1, ((tr1 - 1) % len(id1_f))
            if all_outside1:
                tr1_correct = i1
            else:
                if id1_f[tr1] != -1:
                    tr1_correct = tr1
                elif id1_f[tr1 - 1] != -1:
                    tr1_correct = id1_i1
                else:
                    tr1_correct = tr1
                if i0 == 0:
                    id1_t.append(tr1_correct)

            A = (id0, frozenset((id0_i0, id0_i1)))
            B = (id1, frozenset((id1_i0, id1_i1)))
            key = frozenset((A, B))

            if key not in used_combinations:
                l0a, l0b = id0_c[id0_i0], id0_c[id0_i1]
                l0 = norm_point(l0a), norm_point(l0b)

                l1a, l1b = id1_c[id1_i0], id1_c[id1_i1]
                l1 = norm_point(l1a), norm_point(l1b)

                inter = line_intersection(l0, l1, check_inside=True)
                if inter is not None:
                    if default_shape is not None:
                        inter = np.array(inter).reshape(default_shape)
                    if any(np.array_equiv(inter, x) for x in [l0a, l0b, l1a, l1b]):
                        inter = None
                    conns.append(Interception((id0, tr0_correct), inter, (id1, tr1_correct), key))
                used_combinations.add(key)


def _resolve_complex_associations(completeness, cnts, default_shape, conns, used_combinations):
    """Iteratively complete missing associations across odd connections."""
    to_find_last = None
    limit = 1000
    for _ in range(limit):
        to_find = completeness.generate_incomplete_set()
        if not to_find or to_find_last == to_find:
            break
        to_find_last = to_find

        for (id_val, id0_i0) in to_find:
            id0, id1 = int(id_val), int(not id_val)
            id0_c, id1_c = cnts[id0], cnts[id1]
            for id0_i1 in (((id0_i0 - 1) % len(id0_c)), ((id0_i0 + 1) % len(id0_c))):
                l0a, l0b = id0_c[id0_i0], id0_c[id0_i1]
                l0 = norm_point(l0a), norm_point(l0b)
                for id1_i0 in range(len(id1_c)):
                    id1_i1 = ((id1_i0 - 1) % len(id1_c))
                    l1a, l1b = id1_c[id1_i0], id1_c[id1_i1]
                    l1 = norm_point(l1a), norm_point(l1b)

                    A = (id0, frozenset((id0_i0, id0_i1)))
                    B = (id1, frozenset((id1_i0, id1_i1)))
                    key = frozenset((A, B))

                    if key not in used_combinations:
                        inter = line_intersection(l0, l1, check_inside=True)
                        if inter is not None:
                            if default_shape is not None:
                                inter = np.array(inter).reshape(default_shape)
                            if any(np.array_equiv(inter, x) for x in [l0a, l0b, l1a, l1b]):
                                inter = None
                            if id_val:
                                inter_obj = Interception(A, inter, B, key)
                            else:
                                inter_obj = Interception(B, inter, A, key)
                            conns.append(inter_obj)
                            completeness.register(inter_obj)
                        used_combinations.add(key)
    else:
        raise Exception(f"limit of {limit} iterations exceeded and there are still not complete associations")

    completeness.create_associations()


def cnt_intersection(cnt0, cnt1):
    """Intersect cnt0 with cnt1 using analytical polygon graph clipping."""
    # -1 = outside, 0 = boundary, 1 = inside
    flags0, trans0_raw = cnt_group(cnt0, cnt1)
    flags1, trans1_raw = cnt_group(cnt1, cnt0)

    if np.all(flags0 != -1):
        return [cnt0]
    elif np.all(flags1 != -1):
        return [cnt1]

    try:
        default_shape = cnt0[0].shape
    except (AttributeError, IndexError):
        try:
            default_shape = cnt1[0].shape
        except (AttributeError, IndexError):
            default_shape = None

    trans0 = []
    trans1 = []
    lines = EspList([])
    conns = EspList([])

    trans_raw = trans0_raw, trans1_raw
    trans = trans0, trans1
    cnts = cnt0, cnt1
    flags = flags0, flags1

    used_combinations = set()

    id = 1 if trans1_raw else 0
    id0, id1 = int(id), int(not id)
    id0_c, id1_c = cnts[id0], cnts[id1]
    id0_t, id1_t = trans[id0], trans[id1]
    id0_f, id1_f = flags[id0], flags[id1]

    all_outside0 = np.all(id0_f == -1)
    all_outside1 = np.all(id1_f == -1)

    id0_trans_raw = np.arange(len(id0_f)) if all_outside0 else trans_raw[id0]
    id1_trans_raw = np.arange(len(id1_f)) if all_outside1 else trans_raw[id1]

    _find_initial_interceptions(
        id0_trans_raw, id1_trans_raw, id0_f, id1_f, id0_c, id1_c, id0_t, id1_t,
        id0, id1, all_outside0, all_outside1, default_shape, conns, used_combinations
    )

    if trans0 or trans1:
        for id_idx, t, c, f in ((0, trans0, cnt0, flags0), (1, trans1, cnt1, flags1)):
            used_lines = np.zeros_like(t)
            for i in range(-1, len(t) - 1):
                l = PolyLine(c, f, id_idx, t[i], t[i + 1])
                if l.has_all_points_inside() and not (used_lines[i] and used_lines[i + 1]):
                    used_lines[i] = 1
                    used_lines[i + 1] = 1
                    lines.append(l)
    elif len(conns) == 1:
        return [list(c) for c in conns]

    completeness = Completeness()
    for i in chain(*(lines, conns)):
        completeness.register(i)

    _resolve_complex_associations(completeness, cnts, default_shape, conns, used_combinations)

    tries = 1
    try:
        for j in range(tries + 1):
            completeness = Completeness()
            for i in chain(*(lines, conns)):
                completeness.register(i)
            if not completeness._references:
                break
            elif j >= tries:
                raise IncompleteAssociations("Could not solve conns and lines")
            completeness.create_associations()
    except IncompleteAssociations:
        from intelligent_tracker.figures import interactive_points
        from intelligent_tracker.array_utils import draw_contour_groups
        interactive_points(draw_contour_groups([[cnt0], [cnt1]]), lines + conns)
        completeness.create_associations()
        raise

    contours = []
    for l in chain(*(lines, conns)):
        cnt = list(l.recurse_right())
        if cnt:
            contours.append(cnt)

    return contours


def intersect_analytical(contours):
    """Intersect contours by applying purely analytic operations.

    :param contours: List of contours
    :return: Overlapped contours
    """
    contours = contours[:]
    new_contours = [contours.pop(0)]
    while contours:
        to_intersect = contours.pop()
        new_contours_cache = []
        for new_cnt in new_contours:
            ans = cnt_intersection(new_cnt, to_intersect)
            if ans:
                new_contours_cache.extend([np.array(c, int) for c in ans])
        new_contours = new_contours_cache
        if not new_contours:
            break
    return new_contours


def mixed_intersections(contours, method, img):
    """Placeholder for mixed analytical/raster intersection evaluation."""
    pass

