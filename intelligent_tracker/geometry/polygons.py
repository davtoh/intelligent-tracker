"""Polygonal chain representations, port connections, and recursive traversals."""

from typing import Any, Optional

from intelligent_tracker.geometry.indexing import (
    generate_poly_indexes,
    resolve_poly_connections,
)
from intelligent_tracker.geometry.primitives import (
    IncompleteAssociations,
    NotInvertible,
)


class PolyPortAccessMixin:
    """Property getters and setters for left/right ports and IDs."""

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


class PolyPortLinkMixin:
    """Port testing, assignment, and group propagation."""

    def test_id(self, id, position):
        return position in self.id_in_ids(id)

    def id_in_ids(self, id):
        indices = []
        cgroup, ckey = id
        for i, (group, key) in enumerate(self.port_ids):
            if cgroup == group and any(k in key for k in ckey):
                indices.append(i)
        return indices

    def give_port_right(self, parent):
        assert parent.test_id(self.id_right, 0) or self.test_id(parent.id_left, 1)
        if self.port_right is None:
            if parent.port_left is not None:
                raise IndexError(f"Port left in guest {type(parent)} already taken")
            self.port_right = parent
            parent.port_left = self
        else:
            raise IndexError(f"Port right in host {type(self)} already taken")

    def give_port_left(self, parent):
        assert parent.test_id(self.id_left, 1) or self.test_id(parent.id_right, 0)
        if self.port_left is None:
            if parent.port_right is not None:
                raise IndexError(f"Port right in guest {type(parent)} already taken")
            self.port_left = parent
            parent.port_right = self
        else:
            raise IndexError(f"Port left in host {type(self)} already taken")

    def give_port_in_index(self, index, parent):
        if index:
            self.give_port_right(parent)
        else:
            self.give_port_left(parent)

    def give_group_id(self, group_id):
        if self._group_id == group_id:
            return
        self._group_id = group_id
        for port in self.ports:
            if port is not None:
                port.give_group_id(group_id=group_id)

    def ports_used(self):
        return all(i is not None for i in self.ports)


class PolyTraversalMixin:
    """Chain inversion and recursive contour point generation."""

    def to_invert(self, parents=None):
        if parents is None:
            parents = set((self,))
        else:
            if self in parents:
                return True
            parents.add(self)

        if len(self) == 1:
            for port in self.ports:
                if port is None:
                    continue
                if not port.to_invert(parents):
                    return False
            return True
        elif all(i is None for i in self.ports):
            return True
        return False

    def invert(self, parents=None, force=False):
        if parents is None:
            if not force and not self.to_invert():
                raise NotInvertible("Cannot be inverted")
            parents = [self]
        else:
            if self in parents:
                return
            parents.append(self)

        for port in self.ports:
            if port is not None:
                port.invert(parents)

        self.ports.reverse()
        self.port_ids.reverse()
        self.apply_on_invert(parents=parents)
        self._inverted = not self._inverted

    def apply_on_invert(self, parents=None):
        return

    def recurse_right(self, parent=None):
        if self._used:
            return
        if parent is None:
            parent = self
        elif parent is self:
            return

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
            raise Exception(f"Bad connection in {self}-{port}")

    def recurse_left(self, parent=None):
        if self._used:
            return
        if parent is None:
            parent = self
        elif parent is self:
            return

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
            raise Exception(f"Bad connection in {self}-{port}")


class BasePoly(PolyPortAccessMixin, PolyPortLinkMixin, PolyTraversalMixin):
    """Base Class to provide basic port allocation, inversion and selection
    of variables transparently while inverting ports.
    """

    def __init__(self, cnt, flags, port_left, port_right, id_left, id_right, start, stop, key):
        self.cnt = cnt
        self.ports = [port_left, port_right]
        self.port_ids = [self.adequate_id(id_left), self.adequate_id(id_right)]
        self._start = start
        self._stop = stop
        self._inverted = False
        self._used = False
        self._group_id = None
        self.flags = flags
        if key is None:
            key = frozenset(self.port_ids)
        self.key = key

    def compare_key(self, key):
        return key == self.key

    def has_all_points_inside(self):
        flags = self.flags
        if flags is None:
            return True
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
        group, key = id
        try:
            return group, frozenset(key)
        except TypeError:
            return group, frozenset((key,))

    def indexes(self, indices=None, invert=None):
        return generate_poly_indexes(self.cnt, self._start, self._stop, self._inverted, indices, invert)

    def lines_points(self, invert=None):
        cnt = self.cnt
        for i in self.indexes(invert=invert):
            yield cnt[i]

    def process_connections(self, conns, lines):
        return resolve_poly_connections(self, conns, lines)

    def __str__(self):
        l1, l2 = self.id_left
        r1, r2 = self.id_right
        return f"<{l1},{l2}>{list(self)}<{r1},{r2}>"

    __iter__ = lines_points

    def __getitem__(self, indices):
        if isinstance(indices, slice):
            return [self.cnt[i] for i in self.indexes(indices=indices)]
        return self.cnt[next(self.indexes(indices=indices))]

    def __len__(self):
        if self._stop >= self._start:
            return self._stop - self._start + 1
        return len(self.cnt) - self._start + self._stop + 1

    __bool__ = PolyPortLinkMixin.ports_used
    __nonzero__ = __bool__


class Interception(BasePoly):
    """Represents an Intersection point on a contour boundary."""

    def __init__(self, id_left, center, id_right, key):
        super().__init__([center], None, None, None, id_left, id_right, 0, 0, key)


class PolyLine(BasePoly):
    """Represents a Polyline segment along a contour."""

    def __init__(self, cnt, flags, cnt_id, start, stop):
        super().__init__(cnt, flags, None, None, (cnt_id, start), (cnt_id, stop), start, stop, None)
