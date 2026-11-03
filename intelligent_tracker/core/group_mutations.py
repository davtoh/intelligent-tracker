"""Mutation, child attachment, and lifecycle removal mixin for Group."""

from weakref import ref

from intelligent_tracker.core.spaces import Space


class GroupMutationMixin:
    """Mixin encapsulating item addition, removal, and pending mutation dispatch for Group."""

    def give_remove_handle(self, key):
        """
        give handle to safely remove key from Group. This should
        be thread safe and even if Group is on iterations.
        """
        def remove(keyref=ref(key), selfref=ref(self)):
            self = selfref()
            key = keyref()
            if self is not None and key is not None:
                if self._iterating:
                    self._pending_removals.append(key)
                else:
                    del self[key]
        s = f"remove {key}"
        remove.__name__ = s
        remove.__doc__ = s
        return remove

    def _commit_removals(self):
        """
        remove pending removals when it is safe
        """
        l = self._pending_removals
        while l:
            op, val = l.pop()
            if op:
                val()  # execute operation
            else:
                self._safe_discard(val)

    def add_as_child(self, key):
        """
        assign this Group as parent of key and add it to the Group
        """
        key._space_parent = self
        return self.add(key)

    def add_as_contained(self, key):
        """
        assign this Group as container of key and add it to the Group
        """
        self._space_add_child(key)
        return self.add(key)

    def add_as(self, key, parent=False, contained=False):
        """
        add key to the Group as contained or Group as a parent or both
        """
        if parent:
            key._space_parent = self
        if contained:
            self._space_add_child(key)
        return self.add(key)

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
        return key

    def add(self, key):
        """
        Add `key` as an item to this Group, then return the key.

        If `key` is already in the Group, does not add and returns the key
        """
        if self._iterating:
            self._pending_removals.append((1, lambda: self._safe_add(key)))
        else:
            return self._safe_add(key)

    append = add

    def update(self, sequence, as_parent=False, as_contained=False):
        """
        Update the Group with the given iterable sequence, then return
        the returned value by self.add of the last element inserted.
        """
        returned = None
        for item in sequence:
            returned = self.add_as(item, parent=as_parent,
                                   contained=as_contained)
        return returned

    def _safe_pop(self):
        """
        implementation of pop method to be run safely
        """
        if not self.names:
            raise KeyError('Group is empty')

        key, value = self.names.popitem()
        value._space_name_handles.remove(self._group_handle)
        return value

    def pop(self):
        """
        Remove and return the last element from the Group.

        Raises KeyError if the Group is empty.
        """
        if self._iterating:
            self._pending_removals.append((1, self._safe_pop))
        else:
            return self._safe_pop()

    def _safe_discard(self, key):
        """
        implementation of discard method to be run safely
        """
        if not isinstance(key, str):
            key = key.name

        try:
            value = self.names.pop(key)
        except KeyError:
            return
        value._space_name_handles.remove(self._group_handle)
        return value  # sets return None but this can return value

    def discard(self, value):
        """
        Remove an element. Do not raise an exception if absent.
        """
        if self._iterating:
            self._pending_removals.append((0, value))
        else:
            return self._safe_discard(value)

    def _safe_clear(self):
        """
        implementation of clear method to be run safely
        """
        for i in self.names.values():
            i._space_name_handles.remove(self._group_handle)
        self.names.clear()

    def clear(self):
        """
        Remove all items from this Group.
        """
        if self._iterating:
            self._pending_removals.append((1, self._safe_clear))
        else:
            return self._safe_clear()

    def clear_in_space(self):
        """
        clear objects from group, other groups and space
        """
        for o in self:
            o._space_delete()

