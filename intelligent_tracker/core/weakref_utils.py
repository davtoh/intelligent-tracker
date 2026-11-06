"""Weak reference utilities and dictionary mappings for Space hierarchies."""

from collections.abc import MutableMapping
from weakref import KeyedRef, WeakValueDictionary, _IterationGuard, ref


class SpaceHandle(MutableMapping):
    """handle names"""
    # https://stackoverflow.com/a/3387975/5288758

    def __init__(self, parent, handle):
        self.parent = parent
        self.handle = handle

    def change_name(self, old_name, new_name, obj):
        self.handle[new_name] = self.handle.pop(old_name)

    def remove_name(self, name):
        # self.handle.pop(name)
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
    __slots__ = ('real_data',)

    def __new__(type, ob, callback=None, key=None, real_data=None):
        self = ref.__new__(type, ob, callback)
        self.key = key
        self.real_data = real_data
        return self

    def __init__(self, ob, callback=None, key=None, real_data=None):
        super().__init__(ob, callback, key)

    def __call__(self, *args, **kwargs):
        ans = super().__call__(*args, **kwargs)
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

