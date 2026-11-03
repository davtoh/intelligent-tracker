"""Spatial tree, coordinate spaces, and hierarchical parenting."""

from abc import ABCMeta
from functools import wraps
from weakref import WeakValueDictionary

from combomethod import combomethod

from intelligent_tracker.core.space_hierarchy import SpaceHierarchyMixin
from intelligent_tracker.core.weakref_utils import (
    SpaceHandle,
    WeakRefDictionary,
)


class MetaSpace(ABCMeta):
    """
    Meta class for the Space which gives the "physics" behaviour of the Space
    """
    def __new__(meta, name, bases, dct):
        init = dct.get('__init__', None)
        if init is not None:
            @wraps(init)
            def __init__(self, *args, **kwargs):
                name = kwargs.pop("name", None)
                parent = kwargs.pop("_space_parent", None)
                init(self, *args, **kwargs)
                self._space_parent = parent
                if name is not None:
                    self.name = name
            dct['__init__'] = __init__
        return super().__new__(meta, name, bases, dct)

    def __init__(cls, name, bases, dct):
        super().__init__(name, bases, dct)


class Space(SpaceHierarchyMixin, metaclass=MetaSpace):
    """
    Anything that is created must have a name attribute and be in the Space
    """
    _space_entities = WeakValueDictionary()
    _space_collect_entities = True

    def __new__(cls, *args, **kwargs):
        self = super().__new__(cls)
        self._space_parent_ = None  # Space object can only have one parent
        self._space_entities[str(id(self))] = self
        self._space_children = SpaceHandle(self, WeakRefDictionary())  # Space children
        self._space_name_handles = set()  # Space positions
        return self

    @property
    def name(self):
        try:
            return self._name
        except AttributeError:
            return str(id(self))

    @name.setter
    def name(self, value):
        """change name of object which by default is id"""
        if value and value != self.name:

            if not isinstance(value, str):
                raise TypeError(f"name must be a string not {type(value)}")
            special = "."
            if any(i in value for i in special):
                raise NameError(f"name must not contain {special}")

            if self._space_parent_ is None:
                future_hierarchy = self._space_hierarchy(value, use_name=False)
                if self._space_hierarchy_in_space(future_hierarchy):
                    parent = self._space_hierarchy(None, use_name=False)
                    if not parent:
                        parent = Space.__name__
                    raise KeyError(f"name '{value}' already exists in parent '{parent}'")
            elif any(value in i for i in self._space_name_handles):
                raise KeyError(f"name '{value}' already exists in managed names")

            old_name = self.name
            for handle in self._space_name_handles:
                handle.change_name(old_name, value, self)

            old_hierarchy = self._space_hierarchy()
            self._name = value
            self._space_correct_hierarchy(old_hierarchy)
            self._name_changed_event(old_name)

    def _space_get_item(self, key=None):
        """
        get an name from space of object and their children.
        """
        if isinstance(key, str):
            key = key.split(".")

        k = key.pop(0)
        if key:
            return self._space_children[k]()._space_get_item(key)
        try:
            index = k.index("*")
            starts = k[:index]
            ends = k[index+1:]
            return {i: j[1]() for i, j in self._space_children.items()
                    if i.startswith(starts) and i.endswith(ends)}
        except ValueError:
            return self._space_children[k]()

    @combomethod
    def _space_get_from_hierarchy(self, key):
        """
        get an name from hierarchy of object. If called from class
        it looks-up object starting from outer Space.
        """
        if isinstance(self, Space):
            key = self._space_hierarchy(key, use_name=False)

        try:
            index = key.index("*")
            starts = key[:index]
            ends = key[index+1:]
            return {i: j for i, j in self._space_entities.items()
                    if i.startswith(starts) and i.endswith(ends)}
        except ValueError:
            return self._space_entities[key]

    @property
    def _space_parent(self):
        try:
            if self._space_parent_ is None:
                return Space
            return self._space_parent_
        except AttributeError:
            return Space

    @_space_parent.setter
    def _space_parent(self, value):
        """
        add a parent to this object to appear in its hierarchy as
        a child.
        """
        if value is Space:
            value = None
        if value != self._space_parent_:
            if value is self:
                raise ValueError("parent cannot be itself")

            if value is not None and self._space_parent_in_parents(value):
                raise ValueError("circular reference in parents")

            if value is None:
                future_hierarchy = self.name
                if self._space_hierarchy_in_space(future_hierarchy):
                    raise KeyError(f"conflicting name '{self.name}' in children of "
                                   f"parent '{Space.__name__}'")
            else:
                value._space_add_child(self)

            old_parent = self._space_parent_
            if old_parent is not None:
                old_parent._space_remove_child(self)

            old_hierarchy = self._space_hierarchy()
            self._space_parent_ = value
            self._space_correct_hierarchy(old_hierarchy)
            self._parent_changed_event(old_parent)

    def _name_changed_event(self, old_name):
        return

    def _parent_changed_event(self, old_parent):
        return


def deco_name(func, ismethod=True):
    """
    wrap function to give always 'name' variable
    """
    if ismethod:
        @wraps(func)
        def _func(self, *args, **kwargs):
            name = kwargs.pop("name", None)
            return func(self, name, *args, **kwargs)
    else:
        @wraps(func)
        def _func(*args, **kwargs):
            name = kwargs.pop("name", None)
            return func(name, *args, **kwargs)
    return _func
