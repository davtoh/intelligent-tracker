"""Ordered set and group management within Space hierarchies."""

from collections import OrderedDict
from collections.abc import MutableSet
from threading import RLock
from weakref import _IterationGuard, ref

from intelligent_tracker.core.group_mutations import GroupMutationMixin
from intelligent_tracker.core.spaces import Space
from intelligent_tracker.core.weakref_utils import SpaceHandle


class GroupHandle(SpaceHandle):

    def change_name(self, old_name, new_name, obj):
        dict_to_update = self.parent.names
        if self.handle is dict_to_update and isinstance(dict_to_update, OrderedDict):
            i = self.parent.index(old_name)
            items = list(dict_to_update.items())
            old_name_, val = items[i]
            if old_name != old_name_ or obj is not val:
                raise RuntimeError("Group change_name operation failed "
                                   "because its index method is broken")
            items[i] = (new_name, val)
            dict_to_update.clear()
            dict_to_update.update(items)
        else:
            self.handle[new_name] = self.handle.pop(old_name)

    def remove_name(self, name):
        self.parent.discard(name)


class Group(Space, GroupMutationMixin, MutableSet):
    """
    Create group of objects withing the Space. This group can contain Space
    objects and organize them hierarchically by assigning them as children,
    as contained or simply adding them as private objects which cannot be
    looked up in the Space.

    The Group can be seen as an Ordered set that can iterate them as list
    and retrieve objects by name or reference as in dictionaries.
    """

    def __init__(self, iterable=None, as_parent=False, as_contained=False):
        self._pending_removals = []
        self._iterating = set()
        self.lock_iteration = RLock()

        def _remove(wr, selfref=ref(self)):
            self = selfref()
            if self is not None:
                if self._iterating:
                    self._pending_removals.append(wr.key)
                else:
                    del self[wr.key]
        self._remove = _remove

        if not hasattr(self, "names"):
            self.names = OrderedDict()
        self._group_handle = self._create_group_handle(self.names)

        if iterable is not None:
            self.update(iterable, as_parent=as_parent,
                        as_contained=as_contained)

    def _create_group_handle(self, handle):
        return GroupHandle(self, handle)

    def __len__(self):
        return len(self.names)

    def _getitem_name(self, name):
        try:
            return self.names[name]
        except KeyError:
            raise KeyError(f"name {name} is not in {self}")

    def __getitem__(self, index):
        if isinstance(index, str):
            return self._getitem_name(index)
        elif hasattr(index, '__index__') or isinstance(index, slice):
            return list(self.names.values())[index]
        elif hasattr(index, '__iter__'):
            return [self[i] for i in index]
        elif isinstance(index, Space) and self._getitem_name(index.name) is index:
            return index
        else:
            raise KeyError(f"'{index}' is not in {self}")

    def copy(self):
        return self.__class__(self)

    def __getstate__(self):
        if len(self) == 0:
            return (None,)
        else:
            return list(self)

    def __setstate__(self, state):
        if state == (None,):
            self.__init__([])
        else:
            self.__init__(state)

    def __contains__(self, key):
        if isinstance(key, str):
            return key in self.names
        else:
            try:
                return self.names[key.name] is key
            except KeyError:
                return False

    def index(self, key):
        if (hasattr(key, '__iter__') and not isinstance(key, str) and
                not isinstance(key, tuple)):
            return [self.index(subkey) for subkey in key]
        elif key not in self:
            raise IndexError(f"{key} not in {self}")
        elif isinstance(key, str):
            for i, j in enumerate(self.names.keys()):
                if j == key:
                    return i
        else:
            for i, j in enumerate(self.names.values()):
                if j is key:
                    return i

    def _safe_iter(self):
        return self.names.values()

    def __iter__(self):
        def safe_iter(self):
            res = None
            try:
                res = self.lock_iteration.acquire(blocking=False)
                with _IterationGuard(self):
                    for i in self._safe_iter():
                        yield i
            finally:
                if res:
                    self.lock_iteration.release()
        return iter(safe_iter(self))

    def reverse(self):
        items = list(reversed(self.names.items()))
        self.names.clear()
        self.names.update(items)

    def __reversed__(self):
        return reversed(self.names.values())

    def __repr__(self):
        if not self:
            return f'{self.__class__.__name__}()'
        return f'{self.__class__.__name__}({list(self)!r})'

    def __str__(self):
        name = getattr(self, "_name", "")
        if name:
            name = f"<{name}>"
        if not self:
            return f'{self.__class__.__name__}{name}()'
        return f'{self.__class__.__name__}{name}({list(self)!r})'

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.names == other.names
        try:
            other_as_set = set(other)
        except TypeError:
            return False
        else:
            return set(self) == other_as_set

    def __enter__(self):
        self.lock_iteration.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.lock_iteration.release()
