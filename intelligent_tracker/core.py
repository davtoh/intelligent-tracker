#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# import built-in modules
import gc
import sys
from abc import ABCMeta
from functools import wraps
from threading import RLock
from collections.abc import MutableMapping, MutableSet
from collections import namedtuple, OrderedDict, deque
from ordered_set import OrderedSet
from weakref import ref, WeakValueDictionary, KeyedRef, _IterationGuard  # https://stackoverflow.com/a/36788452/5288758

# import third party modules
from .geometry import cnt_check_intersection
from combomethod import combomethod  # https://stackoverflow.com/q/2589690/5288758
from scipy.spatial.distance import euclidean
import numpy as np
import cv2
_cv_ver = cv2.__version__.split('.')
cv_major_ver = _cv_ver[0]
cv_minor_ver = _cv_ver[1] if len(_cv_ver) > 1 else '0'
cv_subminor_ver = _cv_ver[2] if len(_cv_ver) > 2 else '0'
PY3 = sys.version_info[0] == 3
if PY3:
    xrange = range

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


#class HashableDict(dict):
#    def __hash__(self):
#        return id(self)
#
#
#class HashableOrderedDict(OrderedDict):
#    def __hash__(self):
#        return id(self)


class SpaceHandle(MutableMapping):
    """handle names"""
    # https://stackoverflow.com/a/3387975/5288758

    def __init__(self, parent, handle):
        self.parent = parent
        self.handle = handle

    def change_name(self, old_name, new_name, obj):
        self.handle[new_name] = self.handle.pop(old_name)

    def remove_name(self, name):
        #self.handle.pop(name)
        self.parent._space_remove_child(self.handle[name]())

    def __getitem__(self, key):
        return self.handle[self.__keytransform__(key)]

    def __setitem__(self, key, value):
        self.handle[self.__keytransform__(key)] = value

    def __delitem__(self, key):
        del self.handle[self.__keytransform__(key)]

    def __iter__(self):
        return iter(self.handle)

    def __len__(self):
        return len(self.handle)

    def __keytransform__(self, key):
        return key

    def __hash__(self):
        return id(self)


class WeakWatcher(KeyedRef):
    __slots__ = ('real_data', )

    def __new__(type, ob, callback=None, key=None, real_data=None):
        self = ref.__new__(type, ob, callback)
        self.key = key
        self.real_data = real_data
        return self

    def __init__(self, ob, callback=None, key=None, real_data=None):
        super(WeakWatcher, self).__init__(ob, callback, key)

    def __call__(self, *args, **kwargs):
        ans = super(WeakWatcher, self).__call__(*args, **kwargs)
        if ans is None:
            return
        if self.real_data is not None:
            return self.real_data
        return ans

    def _create_new(self, callback=None, key=None):
        real_data = self.real_data
        self.real_data = None  # force watch data to appear
        watch_data = self()
        return self.__class__(watch_data, callback, key, real_data)


class WeakWatcherWithData(WeakWatcher):

    def __new__(type, ob, callback=None, key=None, real_data=None, **kwargs):
        self = ref.__new__(type, ob, callback)
        self.__dict__.update(kwargs)
        self.key = key
        self.real_data = real_data
        return self

    def __init__(self, ob, callback=None, key=None, real_data=None, **kwargs):
        super(WeakWatcher, self).__init__(ob, callback, key)

    def _create_new(self, callback=None, key=None):
        real_data = self.real_data
        self.real_data = None  # force watch data to appear
        return self.__class__(self(), callback, key, real_data,
                              **self.__dict__)


class WeakWatcherDictionary(WeakValueDictionary):
    """Mapping class that references values weakly.

    Entries in the dictionary will be discarded when no strong
    reference to the value exists anymore
    """

    # We inherit the constructor without worrying about the input
    # dictionary; since it uses our .update() method, we get the right
    # checks (if the other dictionary is a WeakValueDictionary,
    # objects are unwrapped on the way out, and we always wrap on the
    # way in).

    def __setitem__watcher(self, key, value, dic=None):
        if dic is None:
            dic = self.data
        if isinstance(value, WeakWatcher):
            dic[key] = value._create_new(callback=self._remove, key=key)
        elif isinstance(value, ref):
            dic[key] = KeyedRef(value(), self._remove, key)
        else:
            dic[key] = KeyedRef(value, self._remove, key)

    def __setitem__(self, key, value):
        if self._pending_removals:
            self._commit_removals()
        self.__setitem__watcher(key, value)

    def setdefault(self, key, default=None):
        try:
            wr = self.data[key]
        except KeyError:
            if self._pending_removals:
                self._commit_removals()
            self.__setitem__watcher(key, default)
            return default
        else:
            return wr()

    def update(*args, **kwargs):
        if not args:
            raise TypeError("descriptor 'update' of 'WeakValueDictionary' "
                            "object needs an argument")
        self, args = args[0], args[1:]
        if len(args) > 1:
            raise TypeError(
                'expected at most 1 arguments, got %d' % len(args))
        dict = args[0] if args else None
        if self._pending_removals:
            self._commit_removals()
        d = self.data
        if dict is not None:
            if not hasattr(dict, "items"):
                dict = type({})(dict)
            for key, o in dict.items():
                self.__setitem__watcher(key, o, dic=d)
        if len(kwargs):
            self.update(kwargs)


class WeakRefDictionary(WeakWatcherDictionary):
    """Mapping class that references values weakly.

    Entries in the dictionary will be discarded when no strong
    reference to the value exists anymore
    """
    # We inherit the constructor without worrying about the input
    # dictionary; since it uses our .update() method, we get the right
    # checks (if the other dictionary is a WeakValueDictionary,
    # objects are unwrapped on the way out, and we always wrap on the
    # way in).

    def __hash__(self):
        return id(self)

    def __getitem__(self, key):
        wr = self.data[key]
        o = wr()
        if o is None:
            raise KeyError(key)
        else:
            return wr

    def copy(self):
        new = WeakValueDictionary()
        for key, wr in self.data.items():
            o = wr()
            if o is not None:
                new[key] = wr
        return new

    __copy__ = copy

    def __deepcopy__(self, memo):
        from copy import deepcopy
        new = self.__class__()
        for key, wr in self.data.items():
            o = wr()
            if o is not None:
                new[deepcopy(key, memo)] = wr
        return new

    def get(self, key, default=None):
        try:
            wr = self.data[key]
        except KeyError:
            return default
        else:
            o = wr()
            if o is None:
                # This should only happen
                return default
            else:
                return wr

    def items(self):
        with _IterationGuard(self):
            for k, wr in self.data.items():
                v = wr()
                if v is not None:
                    yield k, wr

    def values(self):
        with _IterationGuard(self):
            for wr in self.data.values():
                obj = wr()
                if obj is not None:
                    yield wr

    def popitem(self):
        if self._pending_removals:
            self._commit_removals()
        while True:
            key, wr = self.data.popitem()
            o = wr()
            if o is not None:
                return key, wr

    def pop(self, key, *args):
        if self._pending_removals:
            self._commit_removals()
        try:
            wr = self.data.pop(key)
        except KeyError:
            if args:
                return args[0]
            raise
        if wr() is None:
            raise KeyError(key)
        else:
            return wr

    def setdefault(self, key, default=None):
        try:
            wr = self.data[key]
        except KeyError:
            if self._pending_removals:
                self._commit_removals()
            self.__setitem__watcher(key, default)
            return self.data[key]
        else:
            return wr


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
                # initialization
                init(self, *args, **kwargs)
                # after initialization
                # move to parent first as it is likely there
                # won't be name conflict as name is object's id
                self._space_parent = parent
                if name is not None:
                    # change the name in in-place parent's children
                    # and in hierarchy
                    self.name = name
            dct['__init__'] = __init__
        return super(MetaSpace, meta).__new__(meta, name, bases, dct)

    def __init__(cls, name, bases, dct):
        super(MetaSpace, cls).__init__(name, bases, dct)


class Space(metaclass=MetaSpace):
    """
    Anything that is created must have a name attribute and be in the Space
    """
    _space_entities = WeakValueDictionary()
    _space_collect_entities = True

    def __new__(cls, *args, **kwargs):
        self = super(Space, cls).__new__(cls)
        self._space_parent_ = None  # Space object can only have one parent
        self._space_entities[str(id(self))] = self
        self._space_children = SpaceHandle(self, WeakRefDictionary())  # Space children
        self._space_name_handles = set()  # Space positions
        return self

    def _space_correct_hierarchy(self, old_hierarchy):
        """
        private function used to correct an old hierarchy of this
        object and all its children.

        :param old_hierarchy: string of the previous hierarchy
        """
        # register new hierarchy
        new_hierarchy = self._space_hierarchy()
        # change old hierarchy
        self._space_entities[new_hierarchy] = self._space_entities.pop(old_hierarchy)
        # change children's old hierarchies
        for i in self._space_children.values():
            i = i()
            old = new_hierarchy + "." + i.name
            new = old_hierarchy + "." + i.name
            self._space_entities[old] = self._space_entities.pop(new)

    @property
    def name(self):
        # unique name to exist in one place in the space
        try:
            return self._name
        except AttributeError:
            return str(id(self))

    @name.setter
    def name(self, value):
        """change name of object which by default is id"""
        if value and value != self.name:

            # check it is a valid name
            if not isinstance(value, str):
                raise TypeError("name must be a string not {}".format(type(value)))
            special = "."
            if any(i in value for i in special):
                raise NameError("name must not contain {}".format(special))

            # check name is not in hierarchical conflict
            if self._space_parent_ is None:
                # only check in hierarchy if self is in Space
                # because in-place conflict check tests the other cases
                future_hierarchy = self._space_hierarchy(value, use_name=False)
                if self._space_hierarchy_in_space(future_hierarchy):
                    parent = self._space_hierarchy(None, use_name=False)
                    if not parent:
                        parent = Space.__name__
                    raise KeyError("name '{}' already exists in parent '{}'".format(value, parent))
            elif any(value in i for i in self._space_name_handles):
                # check name is not in in-place conflict
                raise KeyError("name '{}' already exists in managed names".format(value))

            # METHOD: IN-PLACE
            # get old name
            old_name = self.name
            # correct name in handles
            for handle in self._space_name_handles:
                handle.change_name(old_name, value, self)
                #handle[value] = handle.pop(old_name)

            # METHOD: HIERARCHICAL
            # get old hierarchy
            old_hierarchy = self._space_hierarchy()
            # assign new name
            self._name = value
            # correct all names
            self._space_correct_hierarchy(old_hierarchy)
            self._name_changed_event(old_name)

    @staticmethod
    def _space_collect():
        """This process is expensive so do not use if not needed"""
        gc.collect()  # force to collect and update space

    def _space_hierarchy(self, key=None, use_name=True):
        """
        get hierarchy of this object

        :param key: name of append in hierarchy. None to not append
        :param use_name: whether to use the name of this object. That is
            if True get the hierarchy until me and append key=child,
            if False get the hierarchy until parent and append key=brother
        :return: hierarchy
        """
        # support to find parent hierarchy
        parent = self._space_parent_
        train = []
        if parent is not None:
            train.append(parent._space_hierarchy())
        if use_name: train.append(self.name)
        if key is not None:
            train.append(key)
        return ".".join(train)

    def _space_hierarchy_in_space(self, hierarchy):
        """
        check a hierarchy is already in the space

        :param hierarchy: string of hierarchy
        :return: True if hierarchy in space else False
        """
        # do not proceed if there is a conflict in hierarchy
        if hierarchy in self._space_entities:
            # ensure hierarchy is updated to use self._space_entities
            if self._space_collect_entities:
                self._space_collect()
            # previous evaluation was lazy, this ones evaluates
            # with updated self._space_entities
            return hierarchy in self._space_entities
        else:
            return False
        
    def _space_get_item(self, key=None):
        """
        get an name from space of object and their children.

        :param key: string of Space object name to lookup. Use "."
            to move under a parent or separate parents using a list.
             Use "*" to find possible matches.
            e.g. "Grand-space-parent.space-parent.my name"
                ["Grand-space-parent","space-parent","my name"]
                "Grand-space-parent.space-parent.my*e"
                ["Grand-space-parent","space-parent","my*e"]
                "Grand-space-parent.space-pa*"
                ["Grand-space-parent","space-pa*"]
        :return:
        """

        if isinstance(key, str):
            # METHOD: HIERARCHICAL
            #return self._space_entities[self._space_hierarchy(key)]
            key = key.split(".")

        # METHOD: IN PLACE
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

        :param key: string of Space object name to lookup. Use "."
            to move under a parent and "*" to find possible matches.
            e.g. "Grand-parent.parent.my name"
                "Grand-parent.parent.my*e"
                "Grand-parent.pa*"
        :return:
        """
        # https://stackoverflow.com/a/7374385/5288758
        if isinstance(self, Space):
            # get parent hierarchy instead of current hierarchy
            key = self._space_hierarchy(key, use_name=False)

        try:
            index = key.index("*")
            starts = key[:index]
            ends = key[index+1:]
            return {i:j for i, j in self._space_entities.items()
                    if i.startswith(starts) and i.endswith(ends)}
        except ValueError:
            return self._space_entities[key]

    @property
    def _space_parent(self):
        # unique parent for hierarchical lookup
        try:
            if self._space_parent_ is None:
                # not having a parent is the same as None
                # and None must refer to Space
                return Space
            return self._space_parent_
        except AttributeError:
            return Space

    @_space_parent.setter
    def _space_parent(self, value):
        """
        add a parent to this object to appear in its hierarchy as
        a child.

        :param value: parent Space object. None to specify outer Space
        """
        if value is Space:
            value = None
        if value != self._space_parent_:
            if value is self:
                raise ValueError("parent cannot be itself")

            if value is not None and self._space_parent_in_parents(value):
                raise ValueError("circular reference in parents")

            # get future position in hierarchy
            if value is None:
                future_hierarchy = self.name
            #else:
            #    future_hierarchy = value._space_hierarchy(key=self.name)

                # do not proceed if there is a conflict in hierarchy
                if self._space_hierarchy_in_space(future_hierarchy):
                    raise KeyError("conflicting name '{}' in children of "
                                   "parent '{}'".format(self.name, Space.__name__))

            # METHOD: IN-PLACE
            # register child in parent
            else:  # if value is not None:
                # this raises if there is a conflicting
                # child of the same name but it can
                # be thrown by the hierarchy tree
                value._space_add_child(self)

            # unregister child in old parent
            old_parent = self._space_parent_
            if old_parent is not None:
                old_parent._space_remove_child(self)

            # METHOD: HIERARCHICAL
            # get old hierarchy
            old_hierarchy = self._space_hierarchy()
            # assign new parent
            self._space_parent_ = value
            # correct all names
            self._space_correct_hierarchy(old_hierarchy)
            # call event
            self._parent_changed_event(old_parent)

    def _space_parent_in_parents(self, parent):
        """
        check a parent is already in the family tree of this object

        :param parent: parent to check in tree
        :return: True if parent in tree else False
        """
        # do not proceed if there is circular reference for parent
        parent_ = parent._space_parent_
        if parent_ is None:
            return False
        elif parent_ is self:
            return True
        else:
            # keep looking into father until found
            return self._space_parent_in_parents(parent_)

    def _space_add_child(self, child):
        """
        add an object in the internal children to appear in the Space
        as inside this object.

        :param child: child Space object
        """
        name = child.name
        if name in self._space_children:
            if self._space_children[name]() is not child:
                raise KeyError("conflicting name '{}' in children of "
                               "parent '{}'".format(child.name, self.name))
            else:
                #print("Warning: {} already in {}".format(child, self))
                struct = self._space_children[name]
                struct._count += 1
                return

        child_ref = WeakWatcherWithData(child)
        child_ref._count = 0
        self._space_children[name] = child_ref
        child._space_name_handles.add(self._space_children)

    def _space_remove_child(self, child):
        """
        remove an object in the internal children to disappear in the Space
        as inside this object.

        :param child: child Space object
        """
        name = child.name
        struct = self._space_children[name]
        struct._count -= 1
        if struct._count <= 0:
            del self._space_children[name]
            child._space_name_handles.remove(self._space_children)

    def _space_delete(self):
        """
        delete Space object to outer Space. That is from all Space
        objects like Groups, parents and containers.
        """
        self._space_parent = None  # break any parent relationship
        name = self.name
        # delete object from all handles, that is the Space in general
        # self._space_name_handles will change size until it reaches 0
        for handle in list(self._space_name_handles):
            handle.remove_name(name)

    def _name_changed_event(self, old_name):
        """
        called when name is changed

        :param old_name: old name of object. new name cam be accessed
            as object.name
        """
        return

    def _parent_changed_event(self, old_parent):
        """
        called when parent is changed

        :param old_parent: old parent of object. If None it is outer Space
        """
        return


def deco_name(func, ismethod=True):
    """
    wrap function to give always 'name' variable
    
    :param func: 
    :param ismethod: 
    :return: 
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


class GroupHandle(SpaceHandle):

    def change_name(self, old_name, new_name, obj):

        dict_to_update = self.parent.names
        if self.handle is dict_to_update and isinstance(dict_to_update, OrderedDict):
            # ordered dict cannot be destroyed and must keep the same order
            i = self.parent.index(old_name)
            items = list(dict_to_update.items())
            old_name_, val = items[i]
            if old_name != old_name_ or obj is not val:
                raise RuntimeError("Group change_name operation failed "
                                   "because its index method is broken")
            items[i] = (new_name, val)  # update new name
            # because OrderedDict order cannot be altered
            # then we need to clear it and re-insert the items
            dict_to_update.clear()
            dict_to_update.update(items)
        else:
            # assume it is a simple dict
            self.handle[new_name] = self.handle.pop(old_name)

    def remove_name(self, name):
        self.parent.discard(name)


class Group(Space, MutableSet):
    """
    Create group of objects withing the Space. This group can contain Space
    objects and organize them hierarchically by assigning them as children,
    as contained or simply adding them as private objects which cannot be
    looked up in the Space.

    The Group can be seen as an Ordered set that can iterate them as list
    and retrieve objects by name or reference as in dictionaries.
    """
    # https://stackoverflow.com/a/3387975/5288758
    # https://github.com/LuminosoInsight/ordered-set/blob/master/ordered_set.py
    # consider https://stackoverflow.com/a/11560258/5288758

    def __init__(self, iterable=None, as_parent=False, as_contained=False):
        # A list of keys to be removed safely. This should be Thread safe!
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
        self._remove = _remove  # callback to give to ref objects

        # dictionary-like object to allocate names
        if not hasattr(self, "names"):
            self.names = OrderedDict()
        # wrap names to a handle registered to this Group
        self._group_handle = self._create_group_handle(self.names)

        # allocate new data in Group
        if iterable is not None:
            #self |= iterable
            self.update(iterable, as_parent=as_parent,
                        as_contained=as_contained)

    def _create_group_handle(self, handle):
        """
        create a GroupHandle wrapping a normal handle to this Group

        :param handle: dictionary-like handle to be wrapped and
            registered to this Group
        :return: GroupHandle instance
        """
        return GroupHandle(self, handle)

    def give_remove_handle(self, key):
        """
        give handle to safely remove key from Group. This should
        be thread safe and even ig Group is on iterations.
        """
        def remove(keyref=ref(key), selfref=ref(self)):
            self = selfref()
            key = keyref()
            if self is not None and key is not None:
                if self._iterating:
                    self._pending_removals.append(key)
                else:
                    del self[key]
        s = "remove " + str(key)
        remove.__name__ = s
        remove.__doc__ = s
        return remove

    def _commit_removals(self):
        """
        remove pending removals when it is safe
        """
        l = self._pending_removals
        # We shouldn't encounter any KeyError, because this method should
        # always be called *before* mutating the dict.
        while l:
            op, val = l.pop()
            if op:
                val()  # execute operation
            else:
                # discard key
                self._safe_discard(val)

    def __len__(self):
        return len(self.names)

    def _getitem_name(self, name):
        """
        this is used instead of self.names[key]
        to show the user an adequate error
        """
        try:
            return self.names[name]
        except KeyError:
            raise KeyError("name {} is not in {}".format(name, self))

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
            return list(self.names.values())[index]
        elif hasattr(index, '__iter__'):
            # if asked for a list of the elements
            return [self[i] for i in index]
        elif isinstance(index, Space) and self._getitem_name(index.name) is index:
            # if index is an object, for membership check
            return index
        else:
            raise KeyError("'{}' is not in {}".format(index, self))

    def copy(self):
        """copy Group contents"""
        return self.__class__(self)

    def __getstate__(self):
        if len(self) == 0:
            # The state can't be an empty list.
            # needs a truthy value, or else __setstate__ won't be run.
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
            raise TypeError("object must be from Space not '{}'".format(key))
        if key.name in self.names:
            if self.names[key.name] is not key:
                raise ValueError("name conflict. there is already an object "
                                 "with name '{}' in this Group".format(key.name))
        else:
            self.names[key.name] = key
            key._space_name_handles.add(self._group_handle)
        return key

    def add(self, key):
        """
        Add `key` as an item to this Group, then return the key.

        If `key` is already in the Group, does not adds and returns the key
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
        #try:
        for item in sequence:
            returned = self.add_as(item, parent=as_parent,
                                   contained=as_contained)
        #except TypeError:
        #    raise ValueError('Argument needs to be an iterable, '
        #                     'got %s' % type(sequence))
        return returned

    def index(self, key):
        """
        Get the index of a given entry, raising an IndexError if it's not
        present.

        `key` can be an iterable of entries that is not a string, in which case
        this returns a list of indices.
        """
        if (hasattr(key, '__iter__') and not isinstance(key, str) and
                not isinstance(key, tuple)):
            return [self.index(subkey) for subkey in key]
        elif key not in self:
            raise IndexError("{} not in {}".format(key, self))
        elif isinstance(key, str):
            # is name
            for i, j in enumerate(self.names.keys()):
                if j == key:
                    return i
        else:
            # is agent
            for i, j in enumerate(self.names.values()):
                if j is key:
                    return i

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
        Remove an element.  Do not raise an exception if absent.

        The MutableSet mixin uses this to implement the .remove() method, which
        *does* raise an error when asked to remove a non-existent item.
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

    def _safe_iter(self):
        """
        implementation of __iter__ method to be run safely
        """
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
            return '%s()' % (self.__class__.__name__,)
        return '%s(%r)' % (self.__class__.__name__, list(self))

    def __str__(self):
        name = getattr(self, "_name", "")
        if name:
            name = "<{}>".format(name)
        if not self:
            return '%s%s()' % (self.__class__.__name__, name)
        return '%s%s(%r)' % (self.__class__.__name__, name, list(self))

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.names == other.names
        try:
            other_as_set = set(other)
        except TypeError:
            # If `other` can't be converted into a set, it's not equal.
            return False
        else:
            return set(self) == other_as_set

    def __enter__(self):
        self.lock_iteration.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.lock_iteration.release()
    

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
        super(CompleteGroup, self).__init__(iterable, as_parent, as_contained)

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
            raise KeyError("'{}' is not in {}".format(index, self))

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
            raise IndexError("{} not in {}".format(key, self))

    def _safe_add(self, key):
        """
        implementation of add method to be run safely
        """
        if not isinstance(key, Space):
            raise TypeError("object must be from Space not '{}'".format(key))
        if key.name in self.names:
            if self.names[key.name] is not key:
                raise ValueError("name conflict. there is already an object "
                                 "with name '{}' in this Group".format(key.name))
        else:  # if key not in self.map:
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


class Agent(Space):
    """
    Anything in the World with an individual behaviour which is movable and
    cannot be in more than one place at a time, that is and Agent. They
    can be observable and have positions in the Space. From here
    anything is derived and populated in the world.
    """
    def __init__(self):
        self._to_compute = True
        self.active = True
        self.visible = True
        self.drawing = None
        self.cnt = None
        self.rotated_box = None

    def _compute(self):
        """
        function executed when internal data must be updated
        """
        self._to_compute = False
        return

    def compute(self):
        """
        update internal data if necessary

        :return True if computed, else false
        """
        if self._to_compute:
            # compute
            self._compute()
        # if computed
        return not self._to_compute

    def computed_vis(self):
        pass

    def raw_vis(self):
        pass

    @staticmethod
    def get_bounding_box_from_cnt(cnt, _type=None):
        return Agent.get_bounding_box_from_rotated_box(
            Agent.get_rotated_box_from_cnt(cnt), _type)

    @staticmethod
    def get_bounding_box_from_rotated_box(rotated_box, _type=None):
        (tx, ty), (sz_x, sz_y), angle = rotated_box
        # get half distance to center
        x, y = sz_x / 2., sz_y / 2.
        if _type is None:
            return tx - x, ty - y, sz_x, sz_y
        else:
            return _type(tx - x), _type(ty - y), _type(sz_x), _type(sz_y)

    @staticmethod
    def get_rotated_box_from_cnt(cnt, _type=None):
        """
        get a rotated box format (center, size, angle)
        from a contour of N points.
        """
        if _type is None:
            return cv2.minAreaRect(cnt)
        else:
            (cx, cy), (x, y), a = cv2.minAreaRect(cnt)
            return (_type(cx), _type(cy)), (_type(x), _type(y)), _type(a)

    @staticmethod
    def get_rotated_box_from_bounding_box(bounding_box, _type=None):
        x, y, sz_x, sz_y = bounding_box
        # get half distance to center
        tx, ty = sz_x / 2., sz_y / 2.
        if _type is None:
            return (x + tx, y + ty), (sz_x, sz_y), 0
        else:
            return ((_type(x + tx), _type(y + ty)),
                    (_type(sz_x), _type(sz_y)), _type(0))

    @staticmethod
    def get_cnt_from_rotated_box(rotated_box, _type=np.int32):
        """
        get a contour of 4 points with format [left-top, right-top,
        right-bottom, left-bottom] from a rotated box with format
        (center, size, angle)
        """
        # format (x,y),(width,height),theta e.g. ((122, 239), (4, 4), 0)
        (tx, ty), (sz_x, sz_y), angle = rotated_box
        # get half distance to center
        x, y = sz_x/2., sz_y/2.
        # construct contour in origin
        cnt_rect = np.array([((-x, -y),), ((x, -y),),
                             ((x, y),), ((-x, y),)], float)#.reshape(-1, 1, 2)

        # create transformation matrix to rotate and translate
        # https://en.wikipedia.org/wiki/Transformation_matrix
        a = angle * np.pi / 180.  # convert from degrees to radians
        c = np.cos(a)
        s = np.sin(a)
        H = np.array([(c, -s, tx),
                      (s, c, ty),
                      (0, 0, 1)], float)

        # apply transformation with desired type
        # https://docs.opencv.org/2.4/modules/core/doc/operations_on_arrays.html#perspectivetransform
        if _type is None:
            return cv2.perspectiveTransform(cnt_rect, H)
        else:
            return _type(cv2.perspectiveTransform(cnt_rect, H))

    @staticmethod
    def get_cnt_from_bounding_box(bounding_box, _type=np.int32):
        return Agent.get_cnt_from_rotated_box(
            Agent.get_rotated_box_from_bounding_box(bounding_box), _type)

    def __json_enco__(self):
        pass

Point = namedtuple('Point', ('x', 'y', 'z'))


class TailItem:
    """TailItem(cnt, rbox, bbox, pt) which behaves like cnt"""
    # based from recordtype('TailItem', ['cnt', 'rbox', 'bbox', 'pt'])
    # why use __slots__
    #   https://stackoverflow.com/a/1816648/5288758

    _fields = ('cnt', 'rbox', 'bbox', 'pt')
    __slots__ = ["_"+i for i in _fields]

    def __init__(self, cnt=None, rbox=None, bbox=None, pt=None):
        if cnt is None and rbox is None and bbox is None:
            raise Exception("must provide at least cnt, rbox or bbox")
        self._cnt = cnt
        self._rbox = rbox
        if bbox is not None:
            bbox = tuple(bbox)
        self._bbox = bbox
        if pt is not None and not isinstance(pt, Point):
            pt = Point(*pt)  # must be iterable
        self._pt = pt

    def point_inside(self, point):
        """
        test whether point is inside contour

        :param point: point or x-coordinate, y-coordinate
        :return: True if inside or the border of contour, else False
        """
        try:
            return cv2.pointPolygonTest(self.cnt, point.pt[:2], False) != -1
        except AttributeError:
            return cv2.pointPolygonTest(self.cnt, point[:2], False) != -1

    def cnt_intersect(self, cnt):
        """
        test whether internal cnt is intersected with external cnt

        :param cnt: external contour
        :return: True if contours intersect, else False
        """
        try:
            return cnt_check_intersection(self.cnt, cnt.cnt)  # TailItem object
        except AttributeError:
            return cnt_check_intersection(self.cnt, cnt)

    def cnt_near(self, cnt, min_dist=None):
        try:
            (x2, y2), r2 = cnt.enclosing_circle()  # TailItem object
        except AttributeError:
            (x2, y2), r2 = cv2.minEnclosingCircle(cnt)
        (x1, y1), r1 = self.enclosing_circle()
        if min_dist is None:
            min_dist = (r1+r2)/2.
        row1 = ((x1-r1, y1), (x1, y1+r1), (x1+r1, y1), (x1, y1-r1))
        row2 = ((x2-r2, y2), (x2, y2+r2), (x2+r2, y2), (x2, y2-r2))
        min_dt = np.inf
        for i in row1:
            for j in row2:
                dt = euclidean(i, j)
                if dt < min_dt:
                    min_dt = dt
                if dt < min_dist:
                    return True, min_dt
        return False, min_dt

    def point_near(self, point, min_dist=50):
        try:
            pt = point.pt[:2]  # TailItem object
        except AttributeError:
            pt = point[:2]
        (x1, y1), r1 = self.enclosing_circle()
        if min_dist is None:
            min_dist = r1
        row1 = ((x1-r1, y1), (x1, y1+r1), (x1+r1, y1), (x1, y1-r1))
        min_dt = np.inf
        for i in row1:
            dt = euclidean(i, pt)
            if dt < min_dt:
                min_dt = dt
            if dt < min_dist:
                return True, min_dt
        return False, min_dt

    def enclosing_circle(self):
        # ((x, y), radius)
        return cv2.minEnclosingCircle(self.cnt)

    @property
    def cnt(self):
        if self._cnt is None:
            if self._rbox is not None:
                self._cnt = Agent.get_cnt_from_rotated_box(self._rbox)
            elif self._bbox is not None:
                self._cnt = Agent.get_cnt_from_bounding_box(self._bbox)
            else:
                raise RuntimeError("no enough information")
        return self._cnt

    @property
    def rbox(self):
        if self._rbox is None:
            if self._cnt is not None:
                self._rbox = Agent.get_rotated_box_from_cnt(self._cnt)
            elif self._bbox is not None:
                self._rbox = Agent.get_rotated_box_from_bounding_box(self._bbox)
            else:
                raise RuntimeError("no enough information")
        return self._rbox

    @property
    def bbox(self):
        if self._bbox is None:
            if self._cnt is not None:
                self._bbox = Agent.get_bounding_box_from_cnt(self._cnt)
            elif self._rbox is not None:
                self._bbox = Agent.get_bounding_box_from_rotated_box(self._rbox)
            else:
                raise RuntimeError("no enough information")
        return self._bbox

    @property
    def pt(self):
        if self._pt is None:
            M = cv2.moments(self.cnt)
            z = M["m00"]
            try:
                x, y = (int(M["m10"] / M["m00"]),
                        int(M["m01"] / M["m00"]))
            except ZeroDivisionError:
                # FIXME zerodivision
                print("ZeroDivisionError with cnt", self.cnt)
                #x, y = self.cnt[0][0]
                raise
            self._pt = Point(x, y, z)
        return self._pt

    # cnt behaviour
    def __len__(self):
        return len(self.cnt)

    def __iter__(self):
        for i in self.cnt:
            yield i

    def __getitem__(self, index):
        return self.cnt[index]

    def __eq__(self, other):
        return (isinstance(other, self.__class__) and self.cnt == other.cnt
                and self.rbox == other.rbox and self.bbox == other.bbox
                and self.pt == other.pt)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return id(self)

    # others
    def _asdict(self):
        return {'cnt': self.cnt, 'rbox': self.rbox, 'bbox': self.bbox,
                'pt': self.pt}

    def __repr__(self):
        return "{cn}(cnt={cnt}, rbox={rbox}, bbox={bbox}, pt={pt})".format(
            cn=self.__class__.__name__, **self._asdict())

    # persistence

    def __getstate__(self):
        return (self._cnt, self._rbox, self._bbox, self._pt)

    def __setstate__(self, state):
        (self._cnt, self._rbox, self._bbox, self._pt) = state