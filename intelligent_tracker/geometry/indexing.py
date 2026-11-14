"""Index generation and connection resolution helpers for polygonal chains."""

from collections import Counter

from intelligent_tracker.geometry.primitives import (
    IncompleteAssociations,
    NotInvertible,
    go_around,
)


def generate_poly_indexes(cnt, start, stop, inverted, indices=None, invert=None):
    """Generate line point indexes with support for slicing, wrapping, and inversions.

    :param cnt: Contour points collection
    :param start: Starting index in cnt
    :param stop: Stopping index in cnt
    :param inverted: Current inversion state of the polygon
    :param indices: Slicing or integer index
    :param invert: User-requested generation inversion flag
    :return: Generator of indices
    """
    _invert = inverted
    if invert:
        _invert = not _invert

    cnt_l = len(cnt)
    if stop >= start:
        ni = stop - start + 1
    else:
        ni = cnt_l - start + stop + 1

    remain = ni
    step = 1

    ind = stop if _invert else start

    if indices is not None:
        if isinstance(indices, slice):
            if indices.step is not None:
                step = indices.step
                if step == 0:
                    raise ValueError(": slice step cannot be zero")
                if step < 0:
                    step = -step
                    _invert = not _invert

            nstart = indices.start if indices.start is not None else 0
            nstop = indices.stop if (indices.stop is not None and indices.stop <= ni) else ni
            remain = nstop - nstart

            if nstart < ni:
                if _invert:
                    ind = (stop - nstart) % cnt_l
                else:
                    ind = (start + nstart) % cnt_l
            else:
                remain = 0
        else:
            f, _ = go_around(indices, ni, negative=True)
            if f:
                raise IndexError(f": index {indices} out of range")
            if indices < 0:
                indices = ni + indices

            if _invert:
                stop = (stop - indices) % cnt_l
                ind = start = stop
            else:
                start = (start + indices) % cnt_l
                ind = stop = start

    if _invert:
        if stop >= start:
            while remain > 0:
                yield ind
                ind -= step
                remain -= step
        else:
            while remain > 0:
                yield ind
                ind = (ind - step) % cnt_l
                remain -= step
    else:
        if stop >= start:
            while remain > 0:
                yield ind
                ind += step
                remain -= step
        else:
            while remain > 0:
                yield ind
                ind = (ind + step) % cnt_l
                remain -= step


def resolve_poly_connections(poly, conns, lines):
    """Process connections if they are simple from group A to B."""
    consumed = getattr(conns, "_used", Counter())
    try:
        index = conns.index(poly)
    except ValueError:
        index = None

    for _ in (0, 1):
        for ci, conn in enumerate(conns):
            if index != ci:
                if poly.port_right is None:
                    try:
                        i = conn.port_ids.index(poly.id_right)
                    except ValueError:
                        pass
                    else:
                        if i == 0:
                            if conn.port_left is None:
                                poly.give_port_right(conn)
                                consumed[ci] += 1
                                if index is not None:
                                    consumed[index] += 1
                        elif conn.port_right is None:
                            try:
                                conn.invert()
                                poly.give_port_right(conn)
                                consumed[ci] += 1
                                if index is not None:
                                    consumed[index] += 1
                            except NotInvertible:
                                pass

                if poly.port_left is None:
                    try:
                        i = conn.port_ids.index(poly.id_left)
                    except ValueError:
                        continue
                    else:
                        if i == 1:
                            if conn.port_right is None:
                                poly.give_port_left(conn)
                                consumed[ci] += 1
                                if index is not None:
                                    consumed[index] += 1
                        elif conn.port_left is None:
                            try:
                                conn.invert()
                                poly.give_port_left(conn)
                                consumed[ci] += 1
                                if index is not None:
                                    consumed[index] += 1
                            except NotInvertible:
                                pass

                if poly.ports_used():
                    break
        else:
            continue
        break
    else:
        if not poly.ports_used():
            raise IncompleteAssociations(
                f"{type(poly)} {poly} did't find an adequate Association"
            )

    conns._used = consumed
    return consumed

