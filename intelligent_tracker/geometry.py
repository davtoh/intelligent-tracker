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
import numpy as np
import cv2
from collections import Counter, OrderedDict
from itertools import chain

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


class NotInvertible(Exception):
    """Exception to determine if an object is not invertible"""
    pass


class IncompleteAssociations(Exception):
    """Exception to raise when a connection could not be determined"""
    pass


def norm_point(pt):
    """normalize point to a tuple (x,y) of native floats for cv2 compatibility"""
    arr = np.asarray(pt).reshape(2)
    return float(arr[0]), float(arr[1])


def bezier(point, line, check=False):
    """
    Apply bezier algorithm to return a value t from 0 to 1 in x and y,
    that is tx and ty, if point is inside line where t would be the
     percentage of the distance from point1 to point2. If point
    is outside line then t<0 or t>1. If line is horizontal then ty is not
    percentage but the distance from the horizontal and conversely if line
    is vertical then tx is not percentage but the distance from the vertical.

    :param point: point
    :param line: (point1, point2)
    :param check: True to check tx and ty and return None if point is not
        between point1 and point2 in the line.
    :return: tx, ty
    """
    px, py = point
    ((x1, y1), (x2, y2)) = line
    dx = (x1-x2)
    dy = (y1-y2)
    # check point is inside lines using Bézier parameters
    # https://en.wikipedia.org/wiki/B%C3%A9zier_curve#Linear_curves
    # dx and dy are 0 then line is not a line but a point
    tx = x1-px
    if dx != 0:
        # in x for line 1
        tx /= dx
        if check and not 0 <= tx <= 1:  # not (t>=0 and t<=1)
            return None
    elif check and px != x1:
        # if dx = 0 then x1 = x2
        return None

    ty = y1-py
    if dy != 0:
        # in y for line 1
        ty /= dy
        if check and not 0 <= ty <= 1:  # not (t>=0 and t<=1)
            return None
    elif check and py != y1:
        # if dy = 0 then y1 = y2
        return None

    # if it passed the tests then return True
    return tx, ty


def line_intersection(line1, line2, check_inside=True):
    """
    Find the intersecting point between to lines

    :param line1: (line1_point1, line1_point2)
    :param line2: (line2_point1, line2_point2)
    :param check_inside: if True and the lines do not cross
        between their points then it is not considered an intersection
        and None is returned
    :return: point
    """
    # https://en.wikipedia.org/wiki/Line%E2%80%93line_intersection
    ((x1, y1), (x2, y2)) = line1
    ((x3, y3), (x4, y4)) = line2
    L2_dx, L1_dx = (x3-x4), (x1-x2)
    L2_dy, L1_dy = (y3-y4), (y1-y2)
    det_denominator = L1_dx*L2_dy - L1_dy*L2_dx
    # When the two lines are parallel or coincident the denominator is zero
    if det_denominator == 0:
        return None
    # get numerators
    A = (x1*y2-y1*x2)
    B = (x3*y4-y3*x4)
    det_1 = A*L2_dx - L1_dx*B
    det_2 = A*L2_dy - L1_dy*B

    # get intersection point
    px = det_1/det_denominator
    py = det_2/det_denominator

    if (not check_inside or check_inside
        and bezier((px, py), line1, check=True)
        and bezier((px, py), line2, check=True)):
        # return intersection point
        return px, py
    return None


def cnt_group(cnt, cnt_cmp, check=False):
    """
    compare cnt pertaining points and give the transitions

    :param cnt: testing cnt
    :param cnt_cmp: comparing cnt
    :param check: True to return immediately if a point from cnt is found
        inside cnt_cmp and with the found flag added to the returned values,
        True for found or False for not found and consequently with all the
        flags and transitions plus the found flag.
    :return: (flags, transitions) where flags are 1 when the points from
        cnt which are in cnt_cmp, 0 when when in the contour and -1 when
        they are not inside. The flag is determined by pointPolygonTest.
        transitions is an list of the indices where a flag changes from
        outside to inside or in the contour and vice versa.
        if check is True: (flags, transitions, found)
    """
    assert len(cnt) > 1, "contour must have at least 2 points to test transitions"
    transitions = []
    flags = np.empty(len(cnt), int)
    pt_last = norm_point(cnt[-1])
    old_flag = cv2.pointPolygonTest(cnt_cmp, pt_last, False)
    for i, pt in enumerate(cnt):
        flags[i] = flag = cv2.pointPolygonTest(cnt_cmp, norm_point(pt), False)
        # border flag=0 is considered inside flag=1
        # so there is no transition from flag=0 to flag=1 or vice-versa
        # but from flag=0 to flag=-1 or flag=1 to flag=-1, or vice-versa
        #if (flag < 0 and old_flag >= 0) or (old_flag < 0 and flag >= 0):
        #if old_flag != flag:
        if (flag == -1 and old_flag != -1) or (old_flag == -1 and flag != -1):
            # store where is the transition
            transitions.append(i)
        if check and flag != -1:
            # return until flag was found
            return flags[:i+1], transitions, True
        # update_func flag
        old_flag = flag
    if check:
        return flags, transitions, False
    return flags, transitions


def go_around(index, size, negative=False):
    """
    Correct index to infinitely go around an array. This is equivalent
    to carrected_index = (index % size) but this function offers more
    control.

    :param index: index to correct
    :param size: size of array
    :param negative: True to not correct negative indexes
    :return: (flag, carrected_index) flag indicating that index was corrected
    """
    if not negative or index > size - 1 or index + size < 0:
        new_index = index % size
    else:
        new_index = index

    if index != new_index:
        return True, new_index
    return False, new_index


class BasePoly(object):
    """
    Base Class to provide basic port allocation, inversion and selection
     of variables transparently while inverting ports.
    """

    def __init__(self, cnt, flags,
                 port_left, port_right,
                 id_left, id_right,
                 start, stop, key):
        self.cnt = cnt
        self.ports = [port_left, port_right]
        self.port_ids = [self.adequate_id(id_left),
                         self.adequate_id(id_right)]
        self._start = start
        self._stop = stop
        self._inverted = False
        self._used = False
        self._group_id = None
        self.flags = flags
        # unique identifier to test which points this represents
        if key is None:
            key = frozenset(self.port_ids)
        self.key = key

    def compare_key(self, key):
        return key == self.key

    def has_all_points_inside(self):
        """
        returns True if all points in the lines are inside
         the other object
        """
        flags = self.flags
        if flags is None:
            return True  # no flags thus all points are valid
        there_is_one = False
        for i in self.indexes():
            f = flags[i]
            if f == -1:
                return False
            if f == 1:
                there_is_one = True
        return there_is_one

    @staticmethod
    def adequate_id(id):
        """
        adequate or normalize id to be used with all Poly objects
        """
        group, key = id
        try:
            return group, frozenset(key)
        except TypeError:
            return group, frozenset((key,))

    @property
    def id_left(self):
        return self.port_ids[0]

    @id_left.setter
    def id_left(self, value):
        self.port_ids[0] = value

    @property
    def id_right(self):
        return self.port_ids[1]

    @id_right.setter
    def id_right(self, value):
        self.port_ids[1] = value

    @property
    def port_left(self):
        return self.ports[0]

    @port_left.setter
    def port_left(self, value):
        self.ports[0] = value

    @property
    def port_right(self):
        return self.ports[1]

    @port_right.setter
    def port_right(self, value):
        self.ports[1] = value

    def indexes(self, indices=None, invert=None):
        """
        generate lines' point indexes

        :param invert: invert generations of points
        :return: generator
        """
        # control object inversion with user inversion
        _invert = self._inverted
        if invert:
                _invert = not _invert

        # init starting and stopping point with a step of 1
        start, stop, step = self._start, self._stop, 1
        remain = ni = len(self)  # remaining indices = number of indices or len
        #rotated = False  # flag indicating if index ind goes around array
        # initialize starting index
        if _invert:
            ind = stop
        else:
            ind = start

        # slices support
        if indices is not None:
            if isinstance(indices, slice):
                # for step
                if indices.step is not None:
                    step = indices.step
                    if step == 0:
                        raise ValueError(": slice step cannot be zero")
                    if step < 0:
                        # if step is negative then invert previous inversion
                        step = -step
                        _invert = not _invert

                # user starting index
                nstart = indices.start
                if nstart is None:
                    nstart = 0

                # user stop index
                nstop = indices.stop
                if nstop is None or nstop > ni:
                    nstop = ni

                # calculate remaining indices
                remain = nstop - nstart

                # shift starting index
                if nstart < ni:
                    if _invert:
                        ind = (stop - nstart) % len(self.cnt)
                        #rotated, ind = go_around(stop - nstart, len(self.cnt))
                    else:
                        ind = (start + nstart) % len(self.cnt)
                        #rotated, ind = go_around(start + nstart, len(self.cnt))
                else:
                    remain = 0  # empty slice
            else:
                # here indices is really a single index
                f, _ = go_around(indices, ni, negative=True)
                if f:
                    raise IndexError(": index {} out of range".format(indices))
                # correct negative index
                if indices < 0:
                    indices = ni + indices

                # use index
                if _invert:
                    stop = (stop - indices) % len(self.cnt)
                    ind = start = stop
                else:
                    start = (start + indices) % len(self.cnt)
                    ind = stop = start

        # inversion is remembered until yield is finished
        if _invert:
            if stop >= start:
                while remain > 0:
                    # and ind >= start:
                    yield ind
                    ind -= step
                    remain -= step
            else:
                l = len(self.cnt)
                while remain > 0:
                    # and (not rotated and ind <= stop
                    # or rotated and ind >= start):
                    yield ind
                    ind = (ind-step) % l
                    #f, ind = go_around(ind-step, l)
                    #rotated |= f
                    remain -= step
        else:
            if stop >= start:
                while remain > 0:
                    # and ind <= stop:
                    yield ind
                    ind += step
                    remain -= step
            else:
                l = len(self.cnt)
                while remain > 0:
                    # and (not rotated and ind >= start
                    # or rotated and ind <= stop):
                    yield ind
                    ind = (ind+step) % l
                    #f, ind = go_around(ind+step, l)
                    #rotated |= f
                    remain -= step

    def lines_points(self, invert=None):
        """
        generate points from contours

        :param invert: invert generation
        :return: generator
        """
        cnt = self.cnt
        for i in self.indexes(invert=invert):
            yield cnt[i]

    def process_connections(self, conns, lines):
        """
        Process connections if they are simple from group A to B.

        :param conns: list of group A
        :param lines: list of group B
        :return: consumed Counts
        """
        consumed = getattr(conns, "_used", Counter())
        try:
            # if self is in conns then it must be an Intersection
            index = conns.index(self)
        except ValueError:
            # then self must be a Polyline
            index = None
        for _ in (0, 1):
            for ci, conn in enumerate(conns):
                if index != ci:  # self is not conn:
                    if self.port_right is None:
                        try:
                            i = conn.port_ids.index(self.id_right)
                        except ValueError:
                            pass
                        else:
                            i_expected = 0
                            if i == i_expected:
                                if conn.port_left is None:
                                    self.give_port_right(conn)
                                    consumed[ci] += 1
                                    if index is not None:
                                        consumed[index] += 1
                            elif conn.port_right is None:
                                try:
                                    conn.invert()
                                    self.give_port_right(conn)
                                    consumed[ci] += 1
                                    if index is not None:
                                        consumed[index] += 1
                                except NotInvertible:
                                    pass

                    if self.port_left is None:
                        try:
                            i = conn.port_ids.index(self.id_left)
                        except ValueError:
                            continue
                        else:
                            i_expected = 1
                            if i == i_expected:
                                if conn.port_right is None:
                                    self.give_port_left(conn)
                                    consumed[ci] += 1
                                    if index is not None:
                                        consumed[index] += 1
                            elif conn.port_left is None:
                                try:
                                    conn.invert()
                                    self.give_port_left(conn)
                                    consumed[ci] += 1
                                    if index is not None:
                                        consumed[index] += 1
                                except NotInvertible:
                                    pass

                    if self.ports_used():
                        break
            else:
                continue
            break
        else:
            if not self.ports_used():
                raise IncompleteAssociations("{} {} did't find an "
                                "adequate Association".format(type(self), self))

        conns._used = consumed
        return consumed

    def test_id(self, id, position):
        """
        test id if is in position left or right of port_ids

        :param id: id to test
        :param position: 1 for right, 0 for left
        :return: True for found id in position
        """
        return position in self.id_in_ids(id)

    def id_in_ids(self, id):
        """
        test whether id is in this Poly object and in which indices

        :param id: id to test
        :return: indices where id is in port_ids
        """
        indices = []
        cgroup, ckey = id
        for i, (group, key) in enumerate(self.port_ids):
            if cgroup == group and any((i in key for i in ckey)):
                indices.append(i)
        return indices

    def give_port_right(self, parent):
        """
        safely assign right port to parent

        :param parent: parent Poly object like an Intersection or Polyline
        """
        assert parent.test_id(self.id_right, 0) or self.test_id(parent.id_left, 1)
        if self.port_right is None:
            if parent.port_left is not None:
                raise IndexError("Port left in guest {} already taken".format(type(parent)))
            self.port_right = parent
            parent.port_left = self
        else:
            raise IndexError("Port right in host {} already taken".format(type(self)))

    def give_port_left(self, parent):
        """
        safely assign left port to parent

        :param parent: parent Poly object like an Intersection or Polyline
        """
        assert parent.test_id(self.id_left, 1) or self.test_id(parent.id_right, 0)
        if self.port_left is None:
            if parent.port_right is not None:
                raise IndexError("Port right in guest {} already taken".format(type(parent)))
            self.port_left = parent
            parent.port_right = self
        else:
            raise IndexError("Port left in host {} already taken".format(type(self)))

    def give_port_in_index(self, index, parent):
        """
        give port in position of index

        :param index: 1 for right, 0 for left
        :param parent: parent Poly object
        """
        if index:
            # port right
            self.give_port_right(parent)
        else:
            # port left
            self.give_port_left(parent)

    def give_group_id(self, group_id):
        """
        recursively give group_id to all the connected Poly objects
        """
        if self._group_id == group_id:
            return
        self._group_id = group_id
        for i, port in enumerate(self.ports):
            if port is not None:
                port.give_group_id(group_id=group_id)

    def to_invert(self, parents=None):
        """
        Though any Poly is invertible it would result in processing penalties
        if many Poly objects are connected together and they are inverted.
        Thus this functions return True if all the chain can be easily inverted
        or False if not.

        :param parents: previous parent in the chain.
            Control variable indicating which Poly object was the
            caller or the first to call to_invert to end chain.
        :return: True for easy to invert, False if not
        """
        # prevents recursion
        if parents is None:
            parents = set((self,))  # for fast membership tests
        else:
            if self in parents:
                # return invertible because the decision
                # is from parent
                return True
            parents.add(self)

        if len(self) == 1:
            for port in self.ports:
                # the choice must be port
                if port is None:
                    continue
                if not port.to_invert(parents):
                    return False
            return True
        elif all((i is None for i in self.ports)):
            return True  # if all ports are None return True
        else:
            # if ports are used and recursively they are used
            return False

    def invert(self, parents=None, force=False):
        """
        invert all the chain formed from the connections of Poly objects

        :param parents: previous parent in the chain.
            Control variable indicating which Poly object was the
            caller or the first to call to_invert to end chain.
        :param force:
        :return:
        """
        # prevents recursion
        if parents is None:
            # only run check the first time
            if not force and not self.to_invert():
                raise NotInvertible("Cannot be inverted")
            parents = [self]
        else:
            if self in parents:
                # return invertible because the decision
                # is from parent
                return
            parents.append(self)

        for i, port in enumerate(self.ports):
            if port is not None:
                port.invert(parents)

        # for port
        self.ports.reverse()
        self.port_ids.reverse()
        self.apply_on_invert(parents=parents)
        self._inverted = not self._inverted

    def apply_on_invert(self, parents=None):
        return

    def recurse_right(self, parent=None):
        """
        recursively generate points until a round trip is completed

        :param parent: previous parent in the chain.
            Control variable indicating which Poly object was the
            caller or the first to call to_invert to end chain.
        :return: generator
        """
        if self._used:
            return  # PEP 479 raise StopIteration
        if parent is None:
            parent = self
        elif parent is self:
            return  # PEP 479 raise StopIteration

        # yield points
        for i in self.lines_points():
            yield i
        self._used = True

        port = self.port_right
        if port.port_right is self:
            for i in port.recurse_left(parent=parent):
                    yield i
        elif port.port_left is self:
            for i in port.recurse_right(parent=parent):
                    yield i
        else:
            raise Exception("Bad connection in {}-{}".format(self, port))

    def recurse_left(self, parent=None):
        """
        recursively generate points until a round trip is completed

        :param parent: previous parent in the chain.
            Control variable indicating which Poly object was the
            caller or the first to call to_invert to end chain.
        :return: generator
        """
        if self._used:
            return  # PEP 479 raise StopIteration
        if parent is None:
            parent = self
        elif parent is self:
            return  # PEP 479 raise StopIteration

        # yield points
        for i in self.lines_points(invert=True):
            yield i
        self._used = True

        port = self.port_left
        if port.port_left is self:
            for i in port.recurse_right(parent=parent):
                yield i
        elif port.port_right is self:
            for i in port.recurse_left(parent=parent):
                yield i
        else:
            raise Exception("Bad connection in {}-{}".format(self, port))

    def ports_used(self):
        """
        returns True if left and right ports are assigned
        """
        #return not(self.port_left is None or self.port_right is None)
        return all((i is not None for i in self.ports))

    def __str__(self):
        l1, l2 = self.id_left
        r1, r2 = self.id_right
        return "<{},{}>{}<{},{}>".format(l1, l2, list(self), r1, r2)

    __iter__ = lines_points

    def __getitem__(self, indices):
        if isinstance(indices, slice):
            return [self.cnt[i] for i in self.indexes(indices=indices)]
        else:
            return self.cnt[next(self.indexes(indices=indices))]

    def __len__(self):
        """
        len of the generated indexes
        """
        if self._stop >= self._start:
            return self._stop - self._start + 1
        else:
            return len(self.cnt) - self._start + self._stop + 1

    __bool__ = ports_used
    __nonzero__ = __bool__  # compatibility with python 2


class Interception(BasePoly):
    """
    Represents a Interception
    """
    def __init__(self, id_left, center, id_right, key):
        super(Interception, self).__init__([center], None, None, None, id_left, id_right, 0, 0, key)


class PolyLine(BasePoly):
    """
    Represents a Polyline
    """

    def __init__(self, cnt, flags, cnt_id, start, stop):
        super(PolyLine, self).__init__(cnt, flags, None, None, (cnt_id, start), (cnt_id, stop), start, stop, None)


class Completeness(object):
    """
    Search space to add BasePoly objects and find associations
    """
    def __init__(self):
        self._references = {}

    def add_id(self, id, item):
        if id is None:
            raise Exception("None is not id")
        try:
            ref = self._references[id]
        except KeyError:
            self._references[id] = ref = [0, set()]
        ref[0] += 1
        ref[1].add(item)

    def sub_id(self, id, item):
        ref = self._references[id]
        ref[0] += 1
        ref[1].remove(item)

    def register(self, item):
        """
        register Connection ids

        :param item:
        :return:
        """
        if (len(item) == 1 and item.id_left == item.id_right and
                (item.port_left is None or item.port_right is None)):
            self.add_id(item.id_left, item)
        else:
            if item.port_left is None:
                self.add_id(item.id_left, item)
            if item.port_right is None:
                self.add_id(item.id_right, item)

    def unregister(self, item):
        """
        unregister all ids from a Connection

        :param item:
        :return:
        """
        if item.port_left is not None:
            self.sub_id(item.id_left, item)
        if item.port_right is not None:
            self.sub_id(item.id_right, item)

    def items_counts(self):
        """
        iterate over (id, count)
        """
        for id, (count, ref) in self._references.items():
            yield id, count

    def items_connections(self):
        """
        iterate over (id, references to connections)
        """
        for id, (count, ref) in self._references.items():
            yield id, ref

    def generate_count_dictionary(self):
        """
        get ordered dictionary of count of associations
        """
        # get unique counts to create sorted count dictionary
        counts = np.sort(np.unique([i for i, j in self._references.values()]))
        # allocate ordered keys
        count_dict = OrderedDict([(c,[]) for c in counts])
        # populate keys
        for k, (count, ref) in self._references.items():
            count_dict[count].append((k, ref))
        return count_dict

    def generate_incomplete_set(self):
        """
        create a set with all missing ids
        """
        incomplete = set()
        for link, link_sum in self.items_counts():
            if link_sum % 2:
                id, indexes = link
                try:
                    # if there are several indexes
                    for index in indexes:
                        incomplete.add((id, index))
                except TypeError:
                    # if there is just one index
                    incomplete.add(link)
        return incomplete

    def create_associations(self):
        """
        associate connections in all references
        """

        count_groups = self.generate_count_dictionary()
        for count, groups in count_groups.items():
            if count == 1:
                # special case: single references (int)
                # with general references (set)
                groups_ints = []
                groups_sets = []
                for id, refs in groups:
                    try:
                        if len(id[1]) == 1:
                            groups_ints.append((id, list(refs)[0]))
                        else:
                            groups_sets.append((id, list(refs)[0]))
                    except TypeError:
                        groups_ints.append((id, list(refs)[0]))

                ints_in_sets = []
                for id, ref in groups_ints:
                    pos = []
                    ccnt_id, ckey = id
                    for i, ((cnt_id, key), _) in enumerate(groups_sets):
                        if ccnt_id == cnt_id and any((i in key for i in ckey)):
                            pos.append(i)
                    ints_in_sets.append((pos, id, ref))
                ints_in_sets.sort(key=lambda x: len(x[0]))
                groups2 = []
                for pos, id, ref in ints_in_sets:
                    assert len(pos) < 3
                    while len(pos) > 0:
                        r = pos[0]
                        for c, _, _ in ints_in_sets:
                            try:
                                c.remove(r)
                            except ValueError:
                                pass
                        groups2.append((id, (ref, groups_sets[r][1])))
                for id, refs in groups2:
                    i = [(r.id_in_ids(id), r) for r in refs]
                    # sort by least connections and first Polyline
                    i.sort(key=lambda x: (len(x[0]), not isinstance(x[1], PolyLine)))
                    self.associate(i)
            elif count == 2:
                # special case: complete references
                for id, refs in groups:
                    i = [(r.id_in_ids(id), r) for r in refs]
                    # sort by least connections and first Polyline
                    i.sort(key=lambda x: (len(x[0]), not isinstance(x[1], PolyLine)))
                    self.associate(i)
            elif count == 3:
                for id, refs in groups:
                    # in each group there is a connection
                    # which is a Polyline with one point
                    i = [(r.id_in_ids(id), r) for r in refs]
                    # sort by least connections and first Polyline
                    i.sort(key=lambda x: (len(x[0]), not isinstance(x[1], PolyLine)))
                    indeces_l, c_l = i.pop()
                    if len(indeces_l) == 2:
                        # line with 2 equal ids
                        self.associate(i[0], (indeces_l, c_l))
                        self.associate(i[1], (indeces_l, c_l))
            else:
                # confused associations: these should be left for last
                # and only be made if counts have been reduced
                pill = 0
                # groups[0][1]
                for id, refs in groups:
                    for r in refs:
                        if r._group_id is None:
                            r.give_group_id(pill)
                            # join the ones with the same pill
                            i = [(r.id_in_ids(id), r) for r in refs if r._group_id == pill]
                            if len(i) == 2:
                                # there is a group to close
                                self.associate(i)
                            pill += 1

    def associate(self, *args):
        if len(args) == 1:
            (indeces0, c0), (indeces1, c1) = args[0]
        elif len(args) == 2:
            (indeces0, c0), (indeces1, c1) = args[0], args[1]
        else:
            indeces0, c0, indeces1, c1 = args

        index0 = indeces0[0]
        p0, p1 = c0.ports, c1.ports
        if indeces0 == indeces1:
            # both have ids at the same side
            # invert
            try:
                c1.invert()
                c0.give_port_in_index(index0, c1)
            except NotInvertible:
                c0.invert(force=True)
                c0.give_port_in_index(not index0, c1)
        elif len(indeces1) == 2:
            # second connection is a Polyline with one point
            if p1[not index0] is None:
                # no need to invert
                c0.give_port_in_index(index0, c1)
            else:
                # invert
                try:
                    c1.invert()
                    c0.give_port_in_index(index0, c1)
                except NotInvertible:
                    c0.invert(force=True)
                    c0.give_port_in_index(not index0, c1)
        else:
            # no need to invert
            c0.give_port_in_index(index0, c1)


def cnt_check_intersection(cnt0, cnt1):
    """
    check if normal cnt0 and cnt1 intersect
    """
    # -1 = outside, 0 = boundary, 1 = inside
    # fastplt(draw_contour_groups([[cnt0],[cnt1]]), interpolation="nearest")

    # transitions give the id0_i0 i of the transition; line: i, i-1
    flags0, trans0_raw, found = cnt_group(cnt0, cnt1, True)
    if found:
        # fastest route: when a point in contour is inside another
        return found
    flags1, trans1_raw, found = cnt_group(cnt1, cnt0, True)
    if found:
        # fastest route: when a point in contour is inside another
        return found

    # pair variables to choose with id
    trans_raw = trans0_raw, trans1_raw
    cnts = cnt0, cnt1
    flags = flags0, flags1

    # select id as first contour that must have transitions
    id = 0
    if trans1_raw:
        id = 1

    # selected variables with id
    id0, id1 = int(id), int(not id)
    id0_c, id1_c = cnts[id0], cnts[id1]
    id0_f, id1_f = flags[id0], flags[id1]

    # check
    if np.all(id0_f == -1):  # all_outside0:
        id0_trans_raw = np.arange(len(id0_f))
    else:
        id0_trans_raw = trans_raw[id0]

    if np.all(id1_f == -1):  # all_outside1:
        id1_trans_raw = np.arange(len(id1_f))
    else:
        id1_trans_raw = trans_raw[id1]

    # test connections
    for i0, tr0 in enumerate(id0_trans_raw):
        # get indexes in id0
        id0_i0, id0_i1 = tr0, ((tr0 - 1) % len(id0_f))
        for i1, tr1 in enumerate(id1_trans_raw):

            # get indexes in id1
            id1_i0, id1_i1 = tr1, ((tr1 - 1) % len(id1_f))

            # create line 0 in intersection
            l0a, l0b = id0_c[id0_i0], id0_c[id0_i1]
            l0 = norm_point(l0a), norm_point(l0b)

            # create line 1 in intersection
            l1a, l1b = id1_c[id1_i0], id1_c[id1_i1]
            l1 = norm_point(l1a), norm_point(l1b)

            # get intersection
            if line_intersection(l0, l1, check_inside=True) is not None:
                return True


def cnt_intersection(cnt0, cnt1):
    """
    intersect cnt0 with cnt1
    """
    # -1 = outside, 0 = boundary, 1 = inside
    # fastplt(draw_contour_groups([[cnt0],[cnt1]]), interpolation="nearest")

    # transitions give the id0_i0 i of the transition; line: i, i-1
    flags0, trans0_raw = cnt_group(cnt0, cnt1)
    flags1, trans1_raw = cnt_group(cnt1, cnt0)

    ## fastest route: when a contour is inside another
    if np.all(flags0 != -1):
        return [cnt0]
    elif np.all(flags1 != -1):
        return [cnt1]

    # default point shape
    try:
        default_shape = cnt0[0].shape
    except (AttributeError, IndexError):
        try:
            default_shape = cnt1[0].shape
        except (AttributeError, IndexError):
            default_shape = None

    ## special case of 2 lines
    #if all_outside0 and all_outside1:
        # here it was optimized instead of generalizing the
        # subsequent code to prevent overheating in other cases
        #pass

    # initialize transitions, lines and connections
    class EspList(list):
        """Special list to save statistics"""
    trans0 = []
    trans1 = []
    lines = EspList([])
    conns = EspList([])

    # pair variables to choose with id
    trans_raw = trans0_raw, trans1_raw
    trans = trans0, trans1
    cnts = cnt0, cnt1
    flags = flags0, flags1
    used_flags = np.zeros_like(flags0, int), np.zeros_like(flags1, int)
    # unique key format
    # frozenset(((id0,frozenset((id0_i0, id0_i1))),
    #                   (id1,frozenset((id1_i0, id1_i1)))))
    used_combinations = set()  # https://stackoverflow.com/a/25294938/5288758

    # select id as first contour that must have transitions
    if trans1_raw:
        id = 1
    else:
        id = 0

    # selected variables with id
    id0, id1 = int(id), int(not id)
    id0_c, id1_c = cnts[id0], cnts[id1]
    id0_t, id1_t = trans[id0], trans[id1]
    id0_f, id1_f = flags[id0], flags[id1]
    #id0_u, id1_u = used_flags[id0], used_flags[id1]

    # check
    all_outside0 = np.all(id0_f == -1)
    all_outside1 = np.all(id1_f == -1)

    if all_outside0:
        id0_trans_raw = np.arange(len(id0_f))
    else:
        id0_trans_raw = trans_raw[id0]

    if all_outside1:
        id1_trans_raw = np.arange(len(id1_f))
    else:
        id1_trans_raw = trans_raw[id1]

    ## find connections and correct raw transitions
    for i0, tr0 in enumerate(id0_trans_raw):

        # get indexes in id0
        id0_i0, id0_i1 = tr0, ((tr0 - 1) % len(id0_f))

        # convert trans0_raw to trans0
        # move transitions where -1 to the nearest non -1
        if all_outside0:
            tr0_correct = i0
        else:
            if id0_f[tr0] != -1:
                tr0_correct = tr0
            elif id0_f[tr0-1] != -1:
                tr0_correct = id0_i1
            # append processed transition
            id0_t.append(tr0_correct)

        for i1, tr1 in enumerate(id1_trans_raw):

            # get indexes in id1
            id1_i0, id1_i1 = tr1, ((tr1 - 1) % len(id1_f))

            # convert trans1_raw to trans1
            # move transitions where -1 to the nearest non -1
            if all_outside1:
                tr1_correct = i1
            else:
                if id1_f[tr1] != -1:
                    tr1_correct = tr1
                elif id1_f[tr1-1] != -1:
                    tr1_correct = id1_i1
                # only process once
                if i0 == 0:
                    id1_t.append(tr1_correct)

            # create unique key
            A = (id0, frozenset((id0_i0, id0_i1)))
            B = (id1, frozenset((id1_i0, id1_i1)))
            key = frozenset((A, B))

            # do not repeat connections
            if key not in used_combinations:

                # create line 0 in intersection
                l0a, l0b = id0_c[id0_i0], id0_c[id0_i1]
                l0 = norm_point(l0a), norm_point(l0b)

                # create line 1 in intersection
                l1a, l1b = id1_c[id1_i0], id1_c[id1_i1]
                l1 = norm_point(l1a), norm_point(l1b)

                # get intersection
                inter = line_intersection(l0, l1, check_inside=True)

                if inter is not None:
                    # convert intersection to the same as cnt0 or cnt1
                    if default_shape is not None:
                        inter = np.array(inter).reshape(default_shape)

                    # if inter is already one of the lines boundary
                    # then set it to None to not repeat it.
                    if any(np.array_equiv(inter, x) for x in [l0a, l0b, l1a, l1b]):
                        inter = None
                    # append new Interception
                    conns.append(Interception((id0, tr0_correct), inter, (id1, tr1_correct), key))
                    #conns.append(Interception(A, inter, B, key))
                    #id0_u[id0_i0] += 1
                    #id0_u[id0_i1] += 1
                    #id1_u[id1_i0] += 1
                    #id1_u[id1_i1] += 1

                # add the used combination whether it had a intersection or not
                used_combinations.add(key)

    if trans0 or trans1:
        ## find lines
        for id, t, c, f in ((0, trans0, cnt0, flags0),
                            (1, trans1, cnt1, flags1)):
            # process Lines in trans0
            used_lines = np.zeros_like(t)  # flags to not repeat lines
            for i in range(-1, len(t) - 1):
                # cnt, flags, id, left, right
                l = PolyLine(c, f, id, t[i], t[i + 1])
                if (l.has_all_points_inside() and
                        not (used_lines[i] and used_lines[i + 1])):
                    used_lines[i] = 1
                    used_lines[i + 1] = 1
                    lines.append(l)

        # sort from bigger to smaller to increase the chance of finding connections
        # sort the lines so that single points i.e a line with 1 point
        # are left for last... (this could potentially be risky)
        #lines.sort(key=lambda x: len(x), reverse=True)
    elif len(conns) == 1:  #np.alltrue(used_flags):
        # there are no lines and only all connections remain
        # this represents intersection with pure lines where
        # the lines are not inside any area
        return [list(c) for c in conns]

    ## fastest solving for regular shapes
    # solve associations between lines and connections
    shape_complex = True
    if not shape_complex:
        for l in lines:
            try:
                l.process_connections(conns, lines)
            except IncompleteAssociations:
                shape_complex = True

        # solve connections between connections if there are
        # still unsolved associations
        if not shape_complex:
            remaining_conns = [c for c in conns if not c.ports_used()]
            for c in remaining_conns:
                try:
                    c.process_connections(conns, lines)
                except IncompleteAssociations:
                    shape_complex = True

    ## if there are lines and connections then find associations
    # if there are no lines then the program should not arrive here
    if shape_complex:
        # find if there are odd connections

        completeness = Completeness()
        for i in chain(*(lines, conns)):  # lines + conns
            completeness.register(i)

        to_find_last = None
        limit = 1000
        for no_iterations in range(limit):

            # if there are connections not included find them
            # before we look for all the associations
            to_find = completeness.generate_incomplete_set()

            if not to_find or to_find_last == to_find:
                # end search if all possible associations found
                break

            # update_func last list of indexes
            to_find_last = to_find

            for (id, id0_i0) in to_find:
                # select variables with id
                id0, id1 = int(id), int(not id)
                id0_c, id1_c = cnts[id0], cnts[id1]
                for id0_i1 in (((id0_i0-1) % len(id0_c)),
                                 ((id0_i0+1) % len(id0_c))):
                    # create line 0
                    l0a, l0b = id0_c[id0_i0], id0_c[id0_i1]
                    l0 = norm_point(l0a), norm_point(l0b)
                    for id1_i0 in range(len(id1_c)):

                        # create line 1
                        id1_i1 = ((id1_i0 - 1) % len(id1_c))
                        l1a, l1b = id1_c[id1_i0], id1_c[id1_i1]
                        l1 = norm_point(l1a), norm_point(l1b)

                        # create unique key
                        A = (id0, frozenset((id0_i0, id0_i1)))
                        B = (id1, frozenset((id1_i0, id1_i1)))
                        key = frozenset((A, B))

                        if key not in used_combinations:

                            # find intersection
                            inter = line_intersection(l0, l1, check_inside=True)
                            if inter is not None:
                                # convert intersection to the same as cnt0 or cnt1
                                if default_shape is not None:
                                    inter = np.array(inter).reshape(default_shape)

                                # if inter is already one of the lines boundary
                                # then set it to None to not repeat it.
                                if any(np.array_equiv(inter, x) for x in [l0a, l0b, l1a, l1b]):
                                    inter = None
                                # append new Interception and
                                # prevent future inversions by creating them
                                # in the correct order
                                if id:
                                    inter = Interception(A, inter, B, key)
                                else:
                                    inter = Interception(B, inter, A, key)
                                conns.append(inter)

                                # register ids
                                completeness.register(inter)

                            # add the used combination whether
                            # it had a intersection or not
                            used_combinations.add(key)
        else:
            raise Exception("limit of {} iterations exceeded and there are"
                            "still not complete associations".format(limit))

        completeness.create_associations()

    tries = 1
    try:
        # debug and prevent incomplete associations to
        # produce erroneous contours
        for j in range(tries+1):
            completeness = Completeness()
            for i in chain(*(lines, conns)):  # lines + conns
                completeness.register(i)
            if not completeness._references:
                break
            elif j >= tries:
                raise IncompleteAssociations("Could not solve conns and lines")
            completeness.create_associations()
    except IncompleteAssociations:
        # this is for debugging
        from intelligent_tracker.figures import interactive_points
        from intelligent_tracker.array_utils import draw_contour_groups
        interactive_points(draw_contour_groups([[cnt0], [cnt1]]), lines+conns)
        completeness.create_associations()
        raise

    contours = []
    # process all intersected cnts
    for l in chain(*(lines, conns)):
        cnt = list(l.recurse_right())
        if cnt:
            contours.append(cnt)

    # check algorithm
    #for i in lines: i._used = False
    #for i in conns: i._used = False
    #cnt = list(conns[0].recurse_right())
    #for i in lines: i._used = False
    #for i in conns: i._used = False
    #cnt_ = list(conns[0].recurse_left())
    #assert check_contours([cnt], [cnt_]), "forward and reverse must yield the same indexes"
    #fastplt(draw_contour_groups([[cnt0], [cnt1]]), interpolation="nearest")
    #fastplt(draw_contour_groups([[np.array(c, int)] for c in contours]), interpolation="nearest")
    return contours


def intersect_analytical(contours):
    """
    Intersect contours by applying purely analytic operations. Contrary
    to the pixel approach this should not consume much memory and it can
    yield more precise intersections without adding many points but it
    could take more time for small contours. If resolution is really big
    it can save memory because it does not produce accordingly big binary
    images to obtain the intersections.

    :param contours:
    :return: overlapped contours
    """
    # i thing this will be the slowest and a difficult one to implement
    #assert len(contours) > 1
    contours = contours[:]  # copy
    #fastplt(draw_contour_groups([[c] for c in contours]), interpolation="nearest")
    new_contours = [contours.pop(0)]
    # evaluate all contours
    while contours:
        to_intersect = contours.pop()
        # fastplt(draw_contour_groups([[to_intersect],[new_cnt]]), interpolation="nearest")
        new_contours_cache = []
        for new_cnt in new_contours:
            ans = cnt_intersection(new_cnt, to_intersect)
            if ans:
                new_contours_cache.extend([np.array(c, int) for c in ans])
        new_contours = new_contours_cache
        # fastplt(draw_contour_groups([[np.array(c, int)] for c in new_contours]), interpolation="nearest")
        if not new_contours:
            break

    return new_contours


def mixed_intersections(contours, method, img):
    pass


def draw_drawContours(img, cnt):
    """drawing function used to draw cnt"""
    return cv2.drawContours(img, [cnt], -1, 1, -1)


def draw_fillConvexPoly(img, cnt):
    """
    Draw contour. It cannot draw all the cnt correctly. For it to be
    correct it must be convex.

    :param img:
    :param cnt:
    :return:
    """
    return cv2.fillConvexPoly(img, cnt, 1, cv2.LINE_4)


def draw_fillPoly(img, cnt):
    """drawing function used to draw cnt"""
    return cv2.fillPoly(img, [cnt], 1, cv2.LINE_4)


def intersect_AND(img, contours, function=draw_drawContours):
    """
    Intersect contours by applying AND operations

    :param img: initial binary image
    :param contours: contours to overlap
    :param function: drawing function
    :return: final binary image, overlapped contours
    """
    # create an image filled with zeros, single-channel, same size as img.
    blank = np.zeros(img.shape[0:2])
    # evaluate all contours
    for cnt in contours:
        bn = function(blank.copy(), cnt)
        # now AND the two together
        img = np.logical_and(img, bn)
    return cv2.findContours(img.astype(np.uint8), mode=cv2.RETR_LIST,
                            method=cv2.CHAIN_APPROX_SIMPLE)[:2]


def intersect_ADD(img, contours, function=draw_drawContours):
    """
    Intersect contours by applying ADDING operations and finally thresholding

    :param img: initial binary image
    :param contours: contours to overlap
    :param function: drawing function
    :return: final binary image, overlapped contours
    """
    # create an image filled with zeros, single-channel, same size as img.
    blank = np.zeros(img.shape[0:2])
    num_cnt = len(contours)
    # evaluate all contours
    for cnt in contours:
        bn = function(blank.copy(), cnt)
        # add images together
        img += bn
    # pick all points that sum up to the total additions
    return cv2.findContours((img == (num_cnt+1)).astype(np.uint8),
                            mode=cv2.RETR_LIST,
                            method=cv2.CHAIN_APPROX_SIMPLE)[:2]


# ==============================================================================
# Milestone 3: Retail & Occupancy Analytics Geometry (Tripwires & Zone ROIs)
# ==============================================================================

import time
from dataclasses import dataclass, asdict
from typing import List, Tuple, Dict, Optional, Any, Union


@dataclass
class ZoneEvent:
    """
    Event emitted when a tracked entity interacts with a ZoneROI.
    event_type: 'enter', 'exit', or 'dwell'
    """
    zone_id: str
    track_id: int
    event_type: str  # 'enter', 'exit', 'dwell'
    timestamp: float
    dwell_time: float = 0.0
    centroid: Optional[Tuple[float, float]] = None
    bbox: Optional[Tuple[int, int, int, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TripwireEvent:
    """
    Event emitted when a tracked entity crosses a virtual Tripwire.
    direction: 'in' (A_to_B) or 'out' (B_to_A)
    """
    tripwire_id: str
    track_id: int
    direction: str  # 'in', 'out', 'A_to_B', 'B_to_A'
    timestamp: float
    pt1: Tuple[float, float]
    pt2: Tuple[float, float]
    centroid: Optional[Tuple[float, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def segments_intersect(p1, p2, p3, p4):
    """
    Test whether line segment p1-p2 intersects line segment p3-p4.
    Points are (x, y) tuples.
    """
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (c[0] - a[0]) * (b[1] - a[1])

    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)

    # General intersection case
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    return False


class Tripwire(object):
    """
    Bidirectional virtual tripwire for person / vehicle crossing detection.

    Parameters:
    -----------
    line_segment : Tuple[Tuple[float, float], Tuple[float, float]] or List
        Line coordinates ((x1, y1), (x2, y2))
    name : str
        Unique identifier for the tripwire (e.g. 'store_entrance')
    bidirectional : bool
        If True, tracks crossings in both directions ('in' / 'out')
    color : Tuple[int, int, int]
        BGR color for visualization
    """

    def __init__(self, line_segment, name="tripwire_1", bidirectional=True, color=(0, 255, 255)):
        pt1, pt2 = line_segment
        self.pt1 = (float(pt1[0]), float(pt1[1]))
        self.pt2 = (float(pt2[0]), float(pt2[1]))
        self.name = str(name)
        self.bidirectional = bool(bidirectional)
        self.color = color

        # Counters
        self.total_in = 0
        self.total_out = 0
        self.last_crossed_time = None
        self.event_history = []

        # Vector representation for direction determination
        self.dx = self.pt2[0] - self.pt1[0]
        self.dy = self.pt2[1] - self.pt1[1]

    def check_crossing(self, track_id, prev_centroid, curr_centroid, timestamp=None):
        """
        Check if trajectory between prev_centroid and curr_centroid crossed the tripwire.

        :param track_id: Identifier of the tracked object
        :param prev_centroid: (x, y) coordinates on previous frame
        :param curr_centroid: (x, y) coordinates on current frame
        :param timestamp: Event timestamp (defaults to current time)
        :return: TripwireEvent if crossed, else None
        """
        if prev_centroid is None or curr_centroid is None:
            return None

        p1 = (float(prev_centroid[0]), float(prev_centroid[1]))
        p2 = (float(curr_centroid[0]), float(curr_centroid[1]))

        if not segments_intersect(self.pt1, self.pt2, p1, p2):
            return None

        # Determine crossing direction relative to tripwire vector (pt1 -> pt2)
        # Using 2D cross product: dx * my - dy * mx
        mx = p2[0] - p1[0]
        my = p2[1] - p1[1]
        cross_prod = self.dx * my - self.dy * mx

        if cross_prod > 0:
            direction = "in"
            self.total_in += 1
        else:
            direction = "out"
            self.total_out += 1

        ts = timestamp if timestamp is not None else time.time()
        self.last_crossed_time = ts

        event = TripwireEvent(
            tripwire_id=self.name,
            track_id=int(track_id),
            direction=direction,
            timestamp=ts,
            pt1=self.pt1,
            pt2=self.pt2,
            centroid=p2,
        )
        self.event_history.append(event)
        return event

    def draw(self, frame, color=None, thickness=2, show_counts=True):
        """Draw tripwire line and counter labels onto an image frame."""
        col = color or self.color
        p1 = (int(self.pt1[0]), int(self.pt1[1]))
        p2 = (int(self.pt2[0]), int(self.pt2[1]))

        # Line
        cv2.line(frame, p1, p2, col, thickness, cv2.LINE_AA)

        # Endpoints
        cv2.circle(frame, p1, 4, (0, 0, 255), -1)
        cv2.circle(frame, p2, 4, (255, 0, 0), -1)

        # Direction indicator arrow in the middle
        mid_x = int((p1[0] + p2[0]) / 2)
        mid_y = int((p1[1] + p2[1]) / 2)

        # Normal vector pointing 'in'
        length = np.hypot(self.dx, self.dy)
        if length > 0:
            nx = int(-self.dy / length * 15)
            ny = int(self.dx / length * 15)
            cv2.arrowedLine(frame, (mid_x, mid_y), (mid_x + nx, mid_y + ny), col, 1, tipLength=0.3)

        if show_counts:
            label = "{}: IN {} | OUT {}".format(self.name, self.total_in, self.total_out)
            cv2.putText(
                frame,
                label,
                (mid_x - 40, max(20, mid_y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
        return frame


class ZoneROI(object):
    """
    Polygonal Region of Interest (ROI) for occupancy counting and dwell time monitoring.

    Parameters:
    -----------
    polygon : Union[List[Tuple[float, float]], np.ndarray]
        List of vertices [(x, y), ...] defining the polygonal zone boundary.
    name : str
        Unique identifier for the zone (e.g. 'checkout_queue', 'aisle_3')
    dwell_threshold : float
        Seconds of continuous presence before emitting a 'dwell' event.
    color : Tuple[int, int, int]
        BGR color for boundary and translucent fill.
    """

    def __init__(
        self,
        polygon,
        name="zone_1",
        dwell_threshold=5.0,
        color=(0, 200, 100),
        capacity_limit=None,
    ):
        self.name = str(name)
        self.dwell_threshold = float(dwell_threshold)
        self.color = color
        self.capacity_limit = int(capacity_limit) if capacity_limit is not None else None
        self._threshold_breached = False

        # Normalize polygon points to NumPy array of shape (N, 1, 2) int32 for OpenCV
        pts = []
        for pt in polygon:
            pts.append([float(pt[0]), float(pt[1])])
        self.points = np.array(pts, dtype=np.float32)
        self.contour = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))

        # Occupant tracking: track_id -> dict(entry_time=float, last_seen=float, dwell_emitted=bool)
        self.current_occupants = {}
        self.total_entries = 0
        self.total_exits = 0
        self.max_occupancy = 0
        self.event_history = []

    def contains_point(self, pt):
        """Vectorized point-in-polygon containment test via cv2.pointPolygonTest."""
        p = (float(pt[0]), float(pt[1]))
        return cv2.pointPolygonTest(self.contour, p, False) >= 0

    @property
    def occupancy(self):
        """Current number of active occupants inside the zone."""
        return len(self.current_occupants)

    def update(self, tracks, timestamp=None):
        """
        Update zone state with active tracked entities.

        :param tracks: Dict[track_id, Track] or Dict[track_id, centroid] or List[Track]
        :param timestamp: Current frame timestamp
        :return: List of ZoneEvent instances generated on this frame
        """
        now = timestamp if timestamp is not None else time.time()
        events = []

        # Standardize tracks into Dict[track_id, (centroid, bbox)]
        active_items = {}
        if isinstance(tracks, dict):
            for tid, val in tracks.items():
                if hasattr(val, "centroid"):
                    active_items[int(tid)] = (val.centroid, getattr(val, "bbox", None))
                elif isinstance(val, (tuple, list)) and len(val) >= 2:
                    active_items[int(tid)] = (val[:2], None)
        elif isinstance(tracks, (list, tuple)):
            for trk in tracks:
                tid = getattr(trk, "track_id", id(trk))
                centroid = getattr(trk, "centroid", None)
                bbox = getattr(trk, "bbox", None)
                if centroid is not None:
                    active_items[int(tid)] = (centroid, bbox)

        present_tids = set()

        for tid, (centroid, bbox) in active_items.items():
            if centroid is None:
                continue

            if self.contains_point(centroid):
                present_tids.add(tid)
                if tid not in self.current_occupants:
                    # New entrant
                    self.current_occupants[tid] = {
                        "entry_time": now,
                        "last_seen": now,
                        "dwell_emitted": False,
                        "centroid": centroid,
                        "bbox": bbox,
                    }
                    self.total_entries += 1
                    event = ZoneEvent(
                        zone_id=self.name,
                        track_id=tid,
                        event_type="enter",
                        timestamp=now,
                        dwell_time=0.0,
                        centroid=centroid,
                        bbox=bbox,
                    )
                    events.append(event)
                    self.event_history.append(event)
                else:
                    # Existing occupant
                    occ = self.current_occupants[tid]
                    occ["last_seen"] = now
                    occ["centroid"] = centroid
                    occ["bbox"] = bbox
                    dwell_dur = now - occ["entry_time"]

                    if dwell_dur >= self.dwell_threshold and not occ["dwell_emitted"]:
                        occ["dwell_emitted"] = True
                        event = ZoneEvent(
                            zone_id=self.name,
                            track_id=tid,
                            event_type="dwell",
                            timestamp=now,
                            dwell_time=dwell_dur,
                            centroid=centroid,
                            bbox=bbox,
                        )
                        events.append(event)
                        self.event_history.append(event)

        # Handle exits (occupants no longer inside or no longer tracked)
        departed_tids = [tid for tid in self.current_occupants if tid not in present_tids]
        for tid in departed_tids:
            occ = self.current_occupants.pop(tid)
            dwell_dur = max(0.0, now - occ["entry_time"])
            self.total_exits += 1
            event = ZoneEvent(
                zone_id=self.name,
                track_id=tid,
                event_type="exit",
                timestamp=now,
                dwell_time=dwell_dur,
                centroid=occ.get("centroid"),
                bbox=occ.get("bbox"),
            )
            events.append(event)
            self.event_history.append(event)

        self.max_occupancy = max(self.max_occupancy, len(self.current_occupants))
        return events

    def draw(self, frame, alpha=0.25, color=None, show_label=True):
        """Draw translucent polygon overlay and occupancy badge onto frame."""
        col = color or self.color

        # Translucent fill
        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.contour], col)
        cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)

        # Polygon outline
        cv2.polylines(frame, [self.contour], True, col, 2, cv2.LINE_AA)

        if show_label:
            # Place badge near top-left vertex of polygon
            min_y_idx = np.argmin(self.points[:, 1])
            lx = int(self.points[min_y_idx, 0])
            ly = max(20, int(self.points[min_y_idx, 1]) - 8)

            label = "{}: {} occ".format(self.name, len(self.current_occupants))
            (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (lx, ly - h - 4), (lx + w + 8, ly + 4), (30, 30, 30), -1)
            cv2.putText(frame, label, (lx + 4, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)

        return frame