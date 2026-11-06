#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for core spatial hierarchies and weak watcher dictionaries.

Tests:
1. Space parenting and circular reference prevention.
2. Space hierarchy naming conflict resolution.
3. WeakWatcherDictionary, WeakRefDictionary, and WeakWatcherWithData lifecycle.
"""

import gc
import unittest
from contextlib import contextmanager

from intelligent_tracker.core import (
    WeakWatcherDictionary,
    WeakWatcher,
    WeakRefDictionary,
    WeakWatcherWithData,
    ref,
    Agent,
)


class CustomAssertions:
    """Helper assertions for unittest test cases."""

    @contextmanager
    def assertNotRaises(self, Exception, msg=None):
        try:
            yield
        except Exception:
            msg = self._formatMessage(msg, '{} raised'.format(Exception))
            raise self.failureException(msg)


class TestObject:
    """Mock object used for weakref container testing."""
    pass


class SpaceTestCase(unittest.TestCase, CustomAssertions):
    """Test space hierarchy, parenting constraints, and name collisions."""

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_parenting(self):
        """Test parenting constraints and circular reference prevention."""
        a = Agent(name="a_name")
        b = Agent(name="b_name")
        with self.assertRaises(ValueError):
            # parent cannot be itself
            a._space_parent = a

        b._space_parent = a
        bb = Agent(name="b_name")
        # test child of the same name in future parent
        with self.assertRaises(KeyError):
            bb._space_parent = a
        with self.assertRaises(KeyError):
            b._space_parent = None  # equivalent to Space

        del bb  # delete the cause of the conflict
        with self.assertNotRaises(KeyError):
            b._space_parent = None  # equivalent to Space

        # test cross reference
        a._space_parent = b
        with self.assertRaises(ValueError):
            b._space_parent = a

        # test circular reference
        c = Agent()
        a._space_parent = b
        b._space_parent = c
        # c -> b -> a
        with self.assertRaises(ValueError):
            c._space_parent = a

        d = Agent()
        d._space_parent = a
        # c -> b -> a -> d
        with self.assertRaises(ValueError):
            b._space_parent = d

    def test_hierarchy(self):
        """Test name resolution and collision protection across parent/child groups."""
        a = Agent(name="a_name")
        b = Agent()
        with self.assertRaises(KeyError):
            # name already exists in parent Space
            b.name = "a_name"

        # created group in Space
        my_group = Agent()
        # b added as child, so moved in hierarchy
        b._space_parent = my_group

        with self.assertNotRaises(KeyError):
            b.name = "a_name"

        with self.assertRaises(KeyError):
            a._space_parent = my_group

        a.name = "a_name_changed"

        with self.assertNotRaises(KeyError):
            a._space_parent = my_group

        with self.assertRaises(KeyError):
            a.name = b.name


class WeakDictionaryTestCase(unittest.TestCase, CustomAssertions):
    """Test weak reference dictionary implementations and garbage collection tracking."""

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_WeakWatcherDictionary_basic(self):
        dic = WeakWatcherDictionary()
        a = TestObject()
        b = TestObject()
        dic["a"] = a
        dic["b"] = b
        self.assertEqual(dic["a"], a)
        self.assertEqual(dic["b"], b)
        del a
        gc.collect()
        with self.assertRaises(KeyError):
            dic["a"]

    def test_WeakWatcherDictionary_real_data(self):
        dic = WeakWatcherDictionary()
        a = TestObject()
        b = TestObject()
        dic["a"] = WeakWatcher(a, real_data=[0, ref(a)])
        dic["b"] = WeakWatcher(b, real_data=[0, ref(b)])
        self.assertEqual(dic["a"][1](), a)
        self.assertEqual(dic["b"][1](), b)
        del a
        gc.collect()
        with self.assertRaises(KeyError):
            dic["a"]

    def test_WeakRefDictionary(self):
        dic = WeakRefDictionary()
        a = TestObject()
        b = TestObject()
        dic["a"] = WeakWatcher(a, real_data=[0, ref(a)])
        dic["b"] = WeakWatcher(b, real_data=[0, ref(b)])
        self.assertEqual(dic["a"]()[1](), a)
        self.assertEqual(dic["b"]()[1](), b)
        dic["a_beta"] = dic["a"]
        dic["b_beta"] = dic["b"]
        self.assertEqual(dic["b_beta"]()[1](), b)
        del a
        gc.collect()
        with self.assertRaises(KeyError):
            dic["a"]
        with self.assertRaises(KeyError):
            dic["a_beta"]

    def test_WeakWatcherWithData(self):
        dic = WeakRefDictionary()
        a = TestObject()
        b = TestObject()
        dic["a"] = WeakWatcherWithData(a, real_data=[0, ref(a)], addition=1)
        dic["b"] = WeakWatcherWithData(b, real_data=[0, ref(b)], anything=2)
        self.assertEqual(dic["a"]()[1](), a)
        self.assertEqual(dic["b"]()[1](), b)
        self.assertEqual(dic["a"].addition, 1)
        self.assertEqual(dic["b"].anything, 2)
        dic["a_beta"] = dic["a"]
        dic["b_beta"] = dic["b"]
        self.assertEqual(dic["a_beta"]()[1](), a)
        self.assertEqual(dic["b_beta"]()[1](), b)
        self.assertEqual(dic["a_beta"].addition, 1)
        self.assertEqual(dic["b_beta"].anything, 2)
        del a
        gc.collect()
        with self.assertRaises(KeyError):
            dic["a"]
        with self.assertRaises(KeyError):
            dic["a_beta"]


if __name__ == "__main__":
    unittest.main()

