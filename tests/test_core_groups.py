#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Group and CompleteGroup collections.

Tests:
1. Object inclusion, retrieval, and group parenting.
2. Group-level spatial hierarchy and name conflict isolation.
3. Thread-safe manipulation during iteration and context management.
4. Cascading spatial deletions.
"""

import unittest
from contextlib import contextmanager
from random import random, choice
from time import sleep
from threading import Thread

from intelligent_tracker.core import Agent, Group, CompleteGroup


class CustomAssertions:
    """Helper assertions for unittest test cases."""

    @contextmanager
    def assertNotRaises(self, Exception, msg=None):
        try:
            yield
        except Exception:
            msg = self._formatMessage(msg, '{} raised'.format(Exception))
            raise self.failureException(msg)


class GroupTestCase(unittest.TestCase, CustomAssertions):
    """Test standard Group collection, iteration safety, and hierarchy operations."""

    def setUp(self):
        self.testing_group = Group

    def tearDown(self):
        pass

    def test_Group(self):
        """Test group can check and retrieve correct objects."""
        a = Agent(name="a_name")
        b = Agent()
        not_in = Agent()
        my_group = self.testing_group([a, b])

        # Test group inclusion by object and name
        self.assertTrue(a in my_group and b in my_group)
        self.assertTrue(not_in not in my_group and not_in.name not in my_group)
        self.assertTrue(a.name in my_group and b.name in my_group)

        # Change names and verify inclusion
        b.name = b.name + "_changed"
        a_old_name = a.name
        a.name = a.name + "_changed"
        self.assertTrue(b in my_group and b.name in my_group)
        self.assertTrue(a in my_group and a.name in my_group)
        not_in.name = a_old_name
        self.assertFalse(not_in in my_group or not_in.name in my_group)

        # Group as parent and name conflict scoping
        my_group.update([a, b], as_parent=True)
        self.assertTrue(a in my_group and b in my_group)
        self.assertTrue(not_in not in my_group and not_in.name not in my_group)
        not_in.name = a.name
        self.assertFalse(not_in in my_group)
        self.assertTrue(not_in.name in my_group)

    def test_hierarchy(self):
        """Test group space hierarchy formation without corrupting names."""
        a = Agent(name="a_name")
        b = Agent()
        with self.assertRaises(KeyError):
            b.name = "a_name"

        my_group = self.testing_group()
        my_group.add_as_child(b)

        with self.assertNotRaises(KeyError):
            b.name = "a_name"

        with self.assertRaises(KeyError):
            my_group.add_as_child(a)

        a.name = "a_name_changed"
        with self.assertNotRaises(KeyError):
            my_group.add_as_child(a)

        with self.assertRaises(KeyError):
            a.name = b.name

    def test_safe_manipulation(self):
        """Test additions and deletions during iteration are deferred safely."""
        a = Agent(name="a_name")
        b = Agent(name="b_name")
        c = Agent(name="c_name")
        my_group = self.testing_group([a, b])

        for i, j in enumerate(my_group):
            for k in my_group:
                if j is a:
                    my_group.discard(a)
                    res = my_group.add_as_child(c)
                    self.assertIsNone(res)
            with self.subTest(i=i):
                self.assertTrue(a in my_group)
                self.assertTrue(c not in my_group)

        self.assertTrue(a not in my_group)
        self.assertTrue(b in my_group)
        self.assertTrue(c in my_group)

        d = Agent(name="d_name")
        res = my_group.add_as_child(d)
        self.assertIsNotNone(res)

    def _execute_threaded_trial(self, no_t, iterate_fn):
        """Execute a single threaded trial of with-statement group manipulation."""
        test_order = []
        max_first_insertion = no_t
        insertions = [Agent() for _ in range(int(1 + random() * max_first_insertion))]
        my_group = self.testing_group(insertions)
        first_len = len(my_group)
        t = Thread(target=iterate_fn, args=(my_group, test_order))
        t.start()

        with my_group:
            second_len = len(test_order)
            mapping = {}
            no_insertions = int(random() * max_first_insertion)
            for i in range(no_insertions):
                new_agent = Agent()
                res = my_group.add(new_agent)
                with self.subTest(i=i):
                    self.assertIsNotNone(res)
                test_order.append(res)
                mapping[new_agent] = res

            no_deletions = no_insertions / 2
            for _ in range(int(random() * no_deletions)):
                a = my_group.pop()
                with self.assertNotRaises(
                    ValueError,
                    msg="list.remove(x): x not in list, x={}".format(a),
                ):
                    test_order.remove(mapping.pop(a))

            insertion_len = len(test_order) - second_len

        t.join()
        valid_cases = (first_len + insertion_len, first_len + insertion_len * 2)
        self.assertIn(len(test_order), valid_cases, msg="Test lock failed in try {}".format(no_t + 1))
        self.assertFalse([item for item in test_order if item is None])

    def test_safe_manipulation_with_statement(self):
        """Test thread-safety of Group manipulation under with-statement context."""
        def iterate(group, order_list):
            if choice((True, False)):
                sleep(random() / 3)
            for item in group:
                order_list.append(item)

        for no_t in range(10):
            self._execute_threaded_trial(no_t, iterate)

    def test_space_deletions(self):
        """Test cascading deletion of agents across multiple groups."""
        no_agents = 5
        no_groups = 5
        agents = [Agent() for _ in range(no_agents)]
        groups = [
            self.testing_group(
                agents,
                as_contained=choice((False, True)),
                as_parent=choice((False, True)),
            )
            for _ in range(no_groups)
        ]
        for a in agents:
            for g in groups:
                self.assertTrue(a in g, "failed a step to prove test")
            a._space_delete()
            for g in groups:
                self.assertFalse(a in g, "failed to delete agent in {}".format(g))
            remaining = len(a._space_name_handles)
            self.assertFalse(remaining, "still remain {} handles".format(remaining))

        groups = [
            self.testing_group(
                agents,
                as_contained=choice((False, True)),
                as_parent=choice((False, True)),
            )
            for _ in range(no_groups)
        ]
        groups[0].clear_in_space()
        for g in groups:
            self.assertFalse(len(g), "group '{}' is not empty".format(g))


class CompleteGroupTestCase(GroupTestCase):
    """Test CompleteGroup subclass behavior and invariants."""

    def setUp(self):
        self.testing_group = CompleteGroup


if __name__ == "__main__":
    unittest.main()
