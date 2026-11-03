"""CompleteGroup optimized for high-performance indexing and retrieval."""

from intelligent_tracker.core.groups import Group
from intelligent_tracker.core.spaces import Space


class CompleteGroup(Group):
    """
    Class to create Groups with faster facilities for indexing
    and retrieving from indexes (faster retrieval) at the expense of slightly
    slower times when adding Space objects and an slight increase of memory
    usage. The difference with a pure Group is negligible when managing small
    amounts of data. Use this class when the focus is manipulating indexes and
    comparing data withing or among Groups. For intensive adding and removal
    of objects use a pure Group.
    """

    def __init__(self, iterable=None, as_parent=False, as_contained=False):
        self.items = []  # keep items
        self.map = {}  # keep item and indexes
        self.names = dict()  # keep index names and items
        super().__init__(iterable, as_parent, as_contained)

    def __getitem__(self, index):
        """
        Get the item at a given index.

        If `index` is a slice, you will get back that slice of items.
        If it's the slice [:], exactly the same object is returned.
        (If you want an independent copy of a Group, use `Group.copy()`.)

        If `index` is an iterable, you'll get a list of items
        corresponding to those indices. This is similar to NumPy's
        "fancy indexing" except the same object time is not returned.
        """
        if isinstance(index, str):
            # if looking by name
            return self._getitem_name(index)
        elif hasattr(index, '__index__') or isinstance(index, slice):
            # if asked for a slice of the data
            # it is not returned in the same class as they are registered
            # in the space populating it
            return self.items[index]
        elif hasattr(index, '__iter__'):
            # if asked for a list of the elements
            return [self[i] for i in index]
        elif index in self.map:
            # if index is an object, for membership check
            return index
        else:
            raise KeyError(f"'{index}' is not in {self}")

    def __contains__(self, key):
        if isinstance(key, str):
            return key in self.names
        else:
            return key in self.map

    def index(self, key):
        """
        Get the index of a given entry, raising an IndexError if it's not
        present. `key` can be an iterable of entries that is not a string,
        in which case this returns a list of indices.
        """
        if (hasattr(key, '__iter__') and not isinstance(key, str) and
                not isinstance(key, tuple)):
            return [self.index(subkey) for subkey in key]
        # key can be anything supported by group
        try:
            return self.map[self[key]]
        except KeyError:
            raise IndexError(f"{key} not in {self}")

    def _safe_add(self, key):
        """
        implementation of add method to be run safely
        """
        if not isinstance(key, Space):
            raise TypeError(f"object must be from Space not '{key}'")
        if key.name in self.names:
            if self.names[key.name] is not key:
                raise ValueError("name conflict. there is already an object "
                                 f"with name '{key.name}' in this Group")
        else:
            self.names[key.name] = key
            key._space_name_handles.add(self._group_handle)
            self.map[key] = len(self.items)
            self.items.append(key)
        return self.map[key]

    def _safe_pop(self):
        """
        implementation of pop method to be run safely
        """
        if not self.items:
            raise KeyError('Group is empty')

        elem = self.items[-1]
        del self.items[-1]
        del self.map[elem]
        del self.names[elem.name]
        elem._space_name_handles.remove(self._group_handle)
        return elem

    def _safe_discard(self, key):
        """
        implementation of discard method to be run safely
        """
        if isinstance(key, str):
            try:
                key = self.names[key]
            except KeyError:
                return  # not deleted

        try:
            i = self.map[key]
        except KeyError:
            return  # not deleted

        del self.items[i]
        del self.map[key]
        del self.names[key.name]
        key._space_name_handles.remove(self._group_handle)
        for k, v in self.map.items():
            if v >= i:
                self.map[k] = v - 1
        return key  # sets return None but this can return value

    def _safe_clear(self):
        """
        implementation of clear method to be run safely
        """
        names = self._group_handle
        for i in self.items:
            i._space_name_handles.remove(names)
        self.items.clear()
        names.clear()
        self.map.clear()

    def _safe_iter(self):
        """
        implementation of __iter__ method to be run safely
        """
        return self.items

    def reverse(self):
        self.items.reverse()
        # remap indexes
        for i, key in enumerate(self.items):
            self.map[key] = i

    def __reversed__(self):
        return reversed(self.items)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return len(self) == len(other) and self.items == other.items
        try:
            other_as_set = set(other)
        except TypeError:
            # If `other` can't be converted into a set, it's not equal.
            return False
        else:
            return set(self) == other_as_set

