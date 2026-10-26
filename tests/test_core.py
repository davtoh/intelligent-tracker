#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# import built-in modules
import os
import sys
from contextlib import contextmanager
from threading import Thread
from random import random, choice
from time import sleep

# import third party modules
# Legacy reference (unused in tests):
# from RRtoolbox.lib.root import TimeCode, Magnitude
# import pympler.asizeof  # https://stackoverflow.com/a/1816648/5288758
try:
    import resource
except ImportError:
    resource = None
try:
    import psutil
except ImportError:
    psutil = None

# special variables
#__all__ = []
__author__ = "David Toro"
#__copyright__ = "Copyright 2017, The <name> Project"
#__credits__ = [""]
__license__ = "GPL"
#__version__ = "1.0.0"
__maintainer__ = "David Toro"
__email__ = "davsamirtor@gmail.com"
#__status__ = "Pre-release"

import unittest
from intelligent_tracker.core import (WeakWatcherDictionary, WeakWatcher,
                                      WeakRefDictionary, WeakWatcherWithData,
                                      ref, Group, CompleteGroup, Agent)
import gc


def bytes2MB(b):
    return b/1024.0/1024.0


def mem(print_flag=True):
    # https://stackoverflow.com/q/32167386/5288758
    if resource is not None:
        usage = round(
            bytes2MB(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss), 1)
    elif psutil is not None:
        usage = round(bytes2MB(psutil.Process(os.getpid()).memory_info().rss), 1)
    else:
        usage = 0.0
    if print_flag: print('Memory usage         : % 2.2f MB' % usage)
    return usage


def memory_usage_psutil():
    # return the memory usage in percentage like top
    # https://stackoverflow.com/a/30014612/5288758
    if psutil is not None:
        process = psutil.Process(os.getpid())
        per = process.memory_percent()  # percentage
        mem = bytes2MB(process.memory_full_info().rss)  # total used in MB
    else:
        per, mem = 0.0, 0.0
    return per, mem


import time

class TimeCode:
    """Execution timer context manager (self-contained replacement for legacy RRtoolbox.lib.root.TimeCode)."""
    def __init__(self, msg="", printfunc=print):
        self.msg = msg
        self.printfunc = printfunc
        self.time_start = None
        self.time_end = None
        self._cum_start = None
        self.cumulative_time = 0.0

    def __enter__(self):
        self.time_start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.time_end = time.perf_counter() - self.time_start
        if self.printfunc:
            self.printfunc("{}{:.6f} seconds".format(self.msg, self.time_end))

    def start_cummulative(self):
        self._cum_start = time.perf_counter()

    def end_cummulative(self):
        if self._cum_start is not None:
            delta = time.perf_counter() - self._cum_start
            self.cumulative_time += delta
            self.time_end = delta
            self._cum_start = None


def asizeof(obj):
    """Estimate memory footprint (self-contained fallback for pympler.asizeof)."""
    try:
        import pympler.asizeof
        return pympler.asizeof.asizeof(obj)
    except ImportError:
        return sys.getsizeof(obj)


class CustomAssertions:
    # https://stackoverflow.com/a/15868615/5288758
    @contextmanager
    def assertNotRaises(self, Exception, msg=None):
        # https://stackoverflow.com/a/6181656/5288758
        try:
            yield
        except Exception:
            #raise AssertionError('{} raised{}'.format(Exception, msg))
            msg = self._formatMessage(msg, '{} raised'.format(Exception))
            raise self.failureException(msg)


class TestObject:
    pass


class SpaceTestCase(unittest.TestCase, CustomAssertions):
    def setUp(self):
        "Hook method for setting up the test fixture before exercising it."
        pass

    def tearDown(self):
        "Hook method for deconstructing the test fixture after testing it."
        pass

    def test_parenting(self):
        """test that there won't be name or parent corruption when
        the parent of an Agent is changed"""

        # all are in Space
        a = Agent(name="a_name")
        b = Agent(name="b_name")
        with self.assertRaises(ValueError):
            # parent cannot be itself
            a._space_parent = a

        b._space_parent = a
        bb = Agent(name="b_name")
        # test child of the same name in future parent
        with self.assertRaises(KeyError):
            # parent has child of the same name
            bb._space_parent = a
        with self.assertRaises(KeyError):
            # parent has child of the same name
            b._space_parent = None  # equivalent to Space

        del bb  # delete the cause of the conflict
        with self.assertNotRaises(KeyError):
            # parent has child of the same name
            b._space_parent = None  # equivalent to Space

        # test cross reference
        a._space_parent = b
        with self.assertRaises(ValueError):
            # a has already b as parent
            # so b cannot be child of a
            b._space_parent = a

        # test circular reference
        c = Agent()
        a._space_parent = b  # b is the parent of a
        b._space_parent = c  # c is the parent of b
        # c -> b -> a
        with self.assertRaises(ValueError):
            # a cannot be parent of one of its ancestors
            # a -> c
            c._space_parent = a  # a wants to be the parent of c

        d = Agent()
        d._space_parent = a  # a is the parent of d
        # c -> b -> a -> d
        with self.assertRaises(ValueError):
            # d -> b
            b._space_parent = d  # d wants to be the parent of c

    def test_hierarchy(self):
        """test that there won't be name corruption in hierarchy
        when a name is introduced or changed no matter the place
        or where the name is being changed from"""

        # both are in Space
        a = Agent(name="a_name")
        b = Agent()
        with self.assertRaises(KeyError):
            # name already exists in parent Space
            b.name = "a_name"

        # created group in Sapce
        my_group = Agent()  # my_group = Group()
        # b added as child, so moved in hierarchy
        b._space_parent = my_group  # my_group.add_as_child(b)

        with self.assertNotRaises(KeyError):
            # b can change to the same name like a
            # since it is in another hierarchy under Group
            b.name = "a_name"

        with self.assertRaises(KeyError):
            # a name already exists in parent Group since
            # b has the same name
            a._space_parent = my_group  # my_group.add_as_child(a)

        a.name = "a_name_changed"

        with self.assertNotRaises(KeyError):
            # a name has no conflict now
            a._space_parent = my_group  # my_group.add_as_child(a)

        with self.assertRaises(KeyError):
            # a name cannot change to a name that is in the Group
            a.name = b.name


class WeakDictionaryTestCase(unittest.TestCase, CustomAssertions):
    def setUp(self):
        "Hook method for setting up the test fixture before exercising it."
        pass

    def tearDown(self):
        "Hook method for deconstructing the test fixture after testing it."
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


class GroupTestCase(unittest.TestCase, CustomAssertions):
    def setUp(self):
        "Hook method for setting up the test fixture before exercising it."
        self.testing_group = Group

    def tearDown(self):
        "Hook method for deconstructing the test fixture after testing it."
        pass

    def test_Group(self):
        """test group can check and retrieve correct objects"""
        a = Agent(name="a_name")
        b = Agent()
        not_in = Agent()
        # now objects are not in outer Space but
        # now are registered as inside the group
        my_group = self.testing_group([a, b])
        # test group inclusion and exclusion
        # by the object itself
        self.assertTrue(a in my_group)
        self.assertTrue(b in my_group)
        self.assertFalse(not_in in my_group)
        self.assertTrue(not_in not in my_group)
        # by their names
        self.assertTrue(a.name in my_group)
        self.assertTrue(b.name in my_group)
        self.assertFalse(not_in.name in my_group)
        self.assertTrue(not_in.name not in my_group)

        # change names and test again inclusion and exclusion
        b.name = b.name + "_changed"
        self.assertTrue(b in my_group)
        self.assertTrue(b.name in my_group)
        a_old_name = a.name
        a.name = a.name + "_changed"
        self.assertTrue(a in my_group)
        self.assertTrue(a.name in my_group)
        not_in.name = a_old_name
        self.assertFalse(not_in in my_group)
        self.assertFalse(not_in.name in my_group)

        # now objects are not only registered as inside the group
        # but the group is their parent
        my_group.update([a, b], as_parent=True)
        # by the object itself
        self.assertTrue(a in my_group)
        self.assertTrue(b in my_group)
        self.assertFalse(not_in in my_group)
        self.assertTrue(not_in not in my_group)
        # by their names
        self.assertTrue(a.name in my_group)
        self.assertTrue(b.name in my_group)
        self.assertFalse(not_in.name in my_group)
        self.assertTrue(not_in.name not in my_group)

        # now that "a" is a child of my_group
        # not_in which is a child of Space can have the same name as "a"
        not_in.name = a.name
        self.assertFalse(not_in in my_group)

        # there is no way to know by name that they are different objects
        self.assertTrue(not_in.name in my_group)

    def test_hierarchy(self):
        """test group can form space hierarchies without risk of mangling
            names or not reflecting the space as it should be"""
        # both are in Space
        a = Agent(name="a_name")
        b = Agent()
        with self.assertRaises(KeyError):
            # name already exists in parent Space
            b.name = "a_name"

        # create group in Space
        my_group = self.testing_group()
        # b added as child, so moved in hierarchy
        my_group.add_as_child(b)

        with self.assertNotRaises(KeyError):
            # b can change to the same name like a
            # since it is in another hierarchy under Group
            b.name = "a_name"

        with self.assertRaises(KeyError):
            # a name already exists in parent Group since
            # b has the same name
            my_group.add_as_child(a)

        a.name = "a_name_changed"

        with self.assertNotRaises(KeyError):
            # a name has no conflict now
            my_group.add_as_child(a)

        with self.assertRaises(KeyError):
            # a name cannot change to a name that is in the Group
            a.name = b.name

    def test_safe_manipulation(self):
        """
        test whether additions and deletions while a Group is being
        iterated is done lazy and only when the iterations are finished
        """
        a = Agent(name="a_name")
        b = Agent(name="b_name")
        c = Agent(name="c_name")
        # create group in Space
        my_group = self.testing_group([a, b])
        for i, j in enumerate(my_group):
            for k in my_group:
                if j is a:
                    # do  only once
                    my_group.discard(a)
                    res = my_group.add_as_child(c)
                    # shows that while in loop operation is delayed
                    self.assertIsNone(res)
            with self.subTest(i=i):
                # while in loop no changes are done
                self.assertTrue(a in my_group)
                self.assertTrue(c not in my_group)
        # changes are done after all loops are done
        self.assertTrue(a not in my_group)
        self.assertTrue(b in my_group)
        self.assertTrue(c in my_group)

        d = Agent(name="d_name")
        res = my_group.add_as_child(d)
        # shows that while in not in loop operation is not delayed
        self.assertIsNotNone(res)

    def test_safe_manipulation_with_statement(self):
        """
        This tests the with context with Groups. It demonstrates
        that Groups is thread safe.
        This method sleeps randomly and do not reflect the
         real performance of the Group
        """
        def iterate(group, l):
            if choice((True, False)):
                # sleep enough time to let the other process advance
                sleep(random()/3)
            for i in group:
                l.append(i)

        no_tests = 10
        for no_t in range(no_tests):
            test_order = []
            max_first_insertion = no_t
            insertions = [Agent() for _ in
                          range(int(1 + random() * max_first_insertion))]
            my_group = self.testing_group(insertions)
            first_len = len(my_group)
            t = Thread(target=iterate, args=(my_group, test_order))
            t.start()
            with my_group:
                # in this context the Group should ensure that any operation
                # will be executed when there is not iteration with the
                # Group and that it is secure to do proceed with deletions and
                # additions

                second_len = len(test_order)

                # add operations here
                maping = {}
                no_insertions = int(random() * max_first_insertion)
                for i in range(no_insertions):
                    # ensure method returns something besides None
                    new_agent = Agent()
                    # this can be anything and hopefully except None
                    res = my_group.add(new_agent)
                    with self.subTest(i=i):
                        self.assertIsNotNone(res)
                    test_order.append(res)
                    maping[new_agent] = res  # map custom results

                no_deletions = no_insertions / 2
                for _ in range(int(random() * no_deletions)):
                    # a = choice(insertions)
                    # ensure method returns something besides None
                    a = my_group.pop()
                    with self.assertNotRaises(ValueError,
                        msg="list.remove(x): x not in list, x={}".format(a)):
                        test_order.remove(maping.pop(a))

                # calculate how many operations
                insertion_len = len(test_order) - second_len

            t.join()  # wait until thread finishes
            if len(test_order) == first_len + insertion_len:
                # operations after iteration
                self.assertFalse([i for i in test_order if i is None])
            elif len(test_order) == first_len + insertion_len*2:
                # operations before iteration
                self.assertFalse([i for i in test_order if i is None])
            else:
                self.assertTrue(False, msg="Test lock failed in try {}".format(no_t+1))

    def test_space_deletions(self):
        no_agents = 5
        no_groups = 5
        agents = [Agent() for _ in range(no_agents)]
        groups = [self.testing_group(agents, as_contained=choice((False, True)),
                                     as_parent=choice((False, True)))
                  for _ in range(no_groups)]
        for a in agents:
            for g in groups:
                self.assertTrue(a in g, "failed a step to prove test")
            a._space_delete()
            for g in groups:
                self.assertFalse(a in g, "failed to delete agent in {}".format(g))
            remaining = len(a._space_name_handles)
            self.assertFalse(remaining, "still remain {} handles".format(remaining))

        # test all
        groups = [self.testing_group(agents, as_contained=choice((False, True)),
                                     as_parent=choice((False, True)))
                  for _ in range(no_groups)]
        groups[0].clear_in_space()
        for g in groups:
            self.assertFalse(len(g), "group '{}' is not empty".format(g))



class CompleteGroupTestCase(GroupTestCase):
    def setUp(self):
        "Hook method for setting up the test fixture before exercising it."
        self.testing_group = CompleteGroup


class GroupEfficiencyTestCase(unittest.TestCase, CustomAssertions):
    def setUp(self):
        "Hook method for setting up the test fixture before exercising it."
        self.groups = [Group(), CompleteGroup()]

    def tearDown(self):
        "Hook method for deconstructing the test fixture after testing it."
        self.groups.clear()

    def test_compare(self):
        """
        typical output:

        updating Group with 1000 items: 0.066299 seconds
        Group size 1.84 MB, program 82.00 MB, 1.03% of total memory
        getting agent by index 100 times in Group: 0.005021 seconds which are: i0=0.142 ms, i10=0.049 ms, i20=0.047 ms, i30=0.047 ms, i40=0.047 ms, i50=0.047 ms, i60=0.046 ms, i70=0.047 ms, i80=0.046 ms, i90=0.046 ms, i100=0.047 ms, i110=0.046 ms, i120=0.046 ms, i130=0.046 ms, i140=0.046 ms, i150=0.046 ms, i160=0.046 ms, i170=0.047 ms, i180=0.046 ms, i190=0.057 ms, i200=0.057 ms, i210=0.056 ms, i220=0.057 ms, i230=0.047 ms, i240=0.047 ms, i250=0.046 ms, i260=0.046 ms, i270=0.046 ms, i280=0.046 ms, i290=0.046 ms, i300=0.056 ms, i310=0.057 ms, i320=0.047 ms, i330=0.046 ms, i340=0.046 ms, i350=0.046 ms, i360=0.048 ms, i370=0.046 ms, i380=0.047 ms, i390=0.046 ms, i400=0.046 ms, i410=0.059 ms, i420=0.050 ms, i430=0.066 ms, i440=0.047 ms, i450=0.047 ms, i460=0.046 ms, i470=0.046 ms, i480=0.046 ms, i490=0.046 ms, i500=0.046 ms, i510=0.046 ms, i520=0.046 ms, i530=0.046 ms, i540=0.046 ms, i550=0.046 ms, i560=0.046 ms, i570=0.046 ms, i580=0.046 ms, i590=0.046 ms, i600=0.046 ms, i610=0.046 ms, i620=0.046 ms, i630=0.046 ms, i640=0.046 ms, i650=0.046 ms, i660=0.046 ms, i670=0.046 ms, i680=0.046 ms, i690=0.046 ms, i700=0.046 ms, i710=0.046 ms, i720=0.046 ms, i730=0.046 ms, i740=0.046 ms, i750=0.046 ms, i760=0.097 ms, i770=0.081 ms, i780=0.072 ms, i790=0.052 ms, i800=0.051 ms, i810=0.051 ms, i820=0.073 ms, i830=0.079 ms, i840=0.061 ms, i850=0.047 ms, i860=0.046 ms, i870=0.046 ms, i880=0.047 ms, i890=0.047 ms, i900=0.046 ms, i910=0.046 ms, i920=0.046 ms, i930=0.046 ms, i940=0.046 ms, i950=0.046 ms, i960=0.046 ms, i970=0.046 ms, i980=0.046 ms, i990=0.046 ms
        getting agent by value 100 times in Group: 0.000555 seconds
        getting agent by name 100 times in Group: 0.000281 seconds
        iterating 1000 items in Group 0.000134 seconds
        changing agent name 100 times when Group is used: 0.039076 seconds
        reversing 1000 items in Group 0.000331 seconds
        discarding 100 items by value in Group 0.000508 seconds
        discarding 100 items by name in Group 0.000491 seconds
        discarding 100 items by index in Group 0.005079 seconds
        clearing 700 items in Group 0.000507 seconds

        updating CompleteGroup with 1000 items: 0.129765 seconds
        CompleteGroup size 1.93 MB, program 82.11 MB, 1.04% of total memory
        getting agent by index 100 times in CompleteGroup: 0.000164 seconds which are: i0=0.010 ms, i10=0.002 ms, i20=0.002 ms, i30=0.002 ms, i40=0.001 ms, i50=0.002 ms, i60=0.002 ms, i70=0.002 ms, i80=0.002 ms, i90=0.002 ms, i100=0.001 ms, i110=0.001 ms, i120=0.002 ms, i130=0.002 ms, i140=0.002 ms, i150=0.002 ms, i160=0.002 ms, i170=0.002 ms, i180=0.001 ms, i190=0.001 ms, i200=0.001 ms, i210=0.002 ms, i220=0.001 ms, i230=0.002 ms, i240=0.001 ms, i250=0.001 ms, i260=0.002 ms, i270=0.001 ms, i280=0.001 ms, i290=0.001 ms, i300=0.002 ms, i310=0.001 ms, i320=0.002 ms, i330=0.002 ms, i340=0.002 ms, i350=0.001 ms, i360=0.002 ms, i370=0.002 ms, i380=0.001 ms, i390=0.001 ms, i400=0.001 ms, i410=0.002 ms, i420=0.001 ms, i430=0.001 ms, i440=0.001 ms, i450=0.001 ms, i460=0.001 ms, i470=0.002 ms, i480=0.002 ms, i490=0.001 ms, i500=0.001 ms, i510=0.002 ms, i520=0.001 ms, i530=0.001 ms, i540=0.002 ms, i550=0.002 ms, i560=0.002 ms, i570=0.001 ms, i580=0.001 ms, i590=0.002 ms, i600=0.001 ms, i610=0.001 ms, i620=0.002 ms, i630=0.002 ms, i640=0.001 ms, i650=0.002 ms, i660=0.002 ms, i670=0.001 ms, i680=0.001 ms, i690=0.001 ms, i700=0.002 ms, i710=0.001 ms, i720=0.001 ms, i730=0.002 ms, i740=0.002 ms, i750=0.002 ms, i760=0.002 ms, i770=0.001 ms, i780=0.002 ms, i790=0.001 ms, i800=0.001 ms, i810=0.002 ms, i820=0.002 ms, i830=0.002 ms, i840=0.002 ms, i850=0.001 ms, i860=0.001 ms, i870=0.001 ms, i880=0.001 ms, i890=0.001 ms, i900=0.002 ms, i910=0.002 ms, i920=0.002 ms, i930=0.001 ms, i940=0.001 ms, i950=0.001 ms, i960=0.002 ms, i970=0.001 ms, i980=0.002 ms, i990=0.001 ms
        getting agent by value 100 times in CompleteGroup: 0.000199 seconds
        getting agent by name 100 times in CompleteGroup: 0.000131 seconds
        iterating 1000 items in CompleteGroup 0.000125 seconds
        changing agent name 100 times when CompleteGroup is used: 0.003896 seconds
        reversing 1000 items in CompleteGroup 0.000127 seconds
        discarding 100 items by value in CompleteGroup 0.015910 seconds
        discarding 100 items by name in CompleteGroup 0.014403 seconds
        discarding 100 items by index in CompleteGroup 0.014663 seconds
        clearing 700 items in CompleteGroup 0.002078 seconds

        medium data:

        updating Group with 10000 items: 0.734338 seconds
        Group size 18.20 MB, program 100.61 MB, 1.27% of total memory
        getting agent by index 1000 times in Group: 1.686387 seconds
        getting agent by value 1000 times in Group: 0.006331 seconds
        getting agent by name 1000 times in Group: 0.002857 seconds
        iterating 10000 items in Group 0.002547 seconds
        changing agent name 1000 times when Group is used: 12.072925 seconds
        reversing 10000 items in Group 0.007429 seconds
        discarding 1000 items by value in Group 0.005666 seconds
        discarding 1000 items by name in Group 0.005351 seconds
        discarding 1000 items by index in Group 1.279876 seconds
        clearing 7000 items in Group 0.007442 seconds

        updating CompleteGroup with 10000 items: 7.216077 seconds
        CompleteGroup size 18.85 MB, program 114.74 MB, 1.45% of total memory
        getting agent by index 1000 times in CompleteGroup: 0.003818 seconds
        getting agent by value 1000 times in CompleteGroup: 0.003106 seconds
        getting agent by name 1000 times in CompleteGroup: 0.004088 seconds
        iterating 10000 items in CompleteGroup 0.002455 seconds
        changing agent name 1000 times when CompleteGroup is used: 0.058381 seconds
        reversing 10000 items in CompleteGroup 0.002732 seconds
        discarding 1000 items by value in CompleteGroup 3.114873 seconds
        discarding 1000 items by name in CompleteGroup 2.070081 seconds
        discarding 1000 items by index in CompleteGroup 1.607720 seconds
        clearing 7000 items in CompleteGroup 0.135715 seconds

        big data:

        updating Group with 100000 items: 5.975632 seconds
        Group size 172.69 MB, program 312.57 MB, 3.94% of total memory
        getting agent by index 5 times in Group: 0.126789 seconds
        getting agent by value 5 times in Group: 0.000072 seconds
        getting agent by name 5 times in Group: 0.000022 seconds
        iterating 100000 items in Group 0.032963 seconds
        reversing 100000 items in Group 0.118575 seconds
        getting agent by value 5 times in Group: 0.000088 seconds
        discarding 10000 items in Group 0.101913 seconds
        clearing 90000 items in Group 0.096648 seconds

        updating CompleteGroup with 100000 items: 721.883513 seconds
        CompleteGroup size 183.48 MB, program 382.79 MB, 4.83% of total memory
        getting agent by index 5 times in CompleteGroup: 0.000023 seconds
        getting agent by value 5 times in CompleteGroup: 0.000021 seconds
        getting agent by name 5 times in CompleteGroup: 0.000027 seconds
        iterating 100000 items in CompleteGroup 0.010987 seconds
        reversing 100000 items in CompleteGroup 0.022679 seconds
        getting agent by value 5 times in CompleteGroup: 0.090463 seconds
        discarding 10000 items in CompleteGroup 333.245388 seconds
        clearing 90000 items in CompleteGroup 0.058000 seconds
        """

        no_insertions = 1000
        agents_base = [Agent() for _ in range(no_insertions)]
        for g in self.groups:
            agents = agents_base.copy()
            name = g.__class__.__name__
            with TimeCode("updating {} with {} items: ".format(name, len(agents))):
                g.update(agents, as_parent=True, as_contained=True)
            my_size = bytes2MB(asizeof(g))
            percentage, used = memory_usage_psutil()
            print("{} size {:.2f} MB, program {:.2f} MB, {:.2f}% of total "
                  "memory".format(name, my_size, used, percentage))

            step = 10
            indices = list(range(0, no_insertions, step))
            a_rev = [agents[i] for i in indices]
            retrieval_times = []
            printed = []
            pf = lambda x: printed.append(x)
            with TimeCode("getting agent by index {} times in {}: ".format(len(indices), name), printfunc=pf) as tc:
                # retrieval time test
                for i in indices:
                    tc.start_cummulative()
                    g[i]
                    tc.end_cummulative()
                    retrieval_times.append((i, tc.time_end))
            printed[-1] = printed[-1].strip()
            #printed.append(" which are:")
            #printed.append(",".join(" i{}={}".format(i, Magnitude(j, unit="s", factor="m", precision=3)) for i, j in retrieval_times))
            printed.append("\n")
            for i in printed:
                print(i, end="")
            # real retrieval test
            for i, (j, a) in enumerate(zip(indices, a_rev)):
                #with self.subTest(i=i):
                self.assertIs(a, g[j], "failed retrieval by index in {}".format(name))
                self.assertTrue(j==g.index(a), "failed retrieval of index in {}".format(name))

            with TimeCode("getting agent by value {} times in {}: ".format(len(indices), name)):
                # object inside time test
                for a in a_rev:
                    g[a]
            # real object inside test
            for i, a in enumerate(a_rev):
                #with self.subTest(i=i):
                self.assertIs(a, g[a], "failed retrieval by object in {}".format(name))

            with TimeCode("getting agent by name {} times in {}: ".format(len(indices), name)):
                # retrieval by name time test
                for a in a_rev:
                    g[a.name]
            # real retrieval by name test
            for i, a in enumerate(a_rev):
                #with self.subTest(i=i):
                self.assertIs(a, g[a.name], "failed retrieval by name in {}".format(name))

            with TimeCode("iterating {} items in {} ".format(len(agents), name)):
                for i in g:
                    i

            with TimeCode("changing agent name {} times when {} is used: ".format(len(indices), name)):
                # retrieval by name time test
                for a in a_rev:
                    a.name = a.name + "_changed"
            # real retrieval by name test
            for i, (j, a) in enumerate(zip(indices, a_rev)):
                #with self.subTest(i=i):
                self.assertIs(a, g[a.name], "failed retrieval by name when name changed in {}".format(name))
                self.assertIs(agents[j], g[j], "failed retrieval by index when name changed in {}".format(name))
                self.assertTrue(j==g.index(a), "failed retrieval of index when name changed in {}".format(name))

            with TimeCode("reversing {} items in {} ".format(len(agents), name)):
                g.reverse()

            agents.reverse()  # reflect the changes in the group
            # test reverse values
            for i, a in enumerate(g):
                #with self.subTest(i=i):
                cmp_a = agents[i]
                self.assertIs(a, cmp_a, "failed reverse comparison by iteration in {}".format(name))
                self.assertTrue(g.index(a) == i, "failed reverse comparison by index in {}".format(name))

            # real object discarding test
            to_discard = int(no_insertions*0.1)  # delete 10%
            indices_discard = range(to_discard)
            with TimeCode("discarding {} items by value in {} ".format(to_discard, name)) as tc:
                for i, j in enumerate(indices_discard):
                    a = agents[j]
                    del agents[j]  # reflect the changes in the group
                    tc.start_cummulative()
                    g.discard(a)
                    tc.end_cummulative()
                    #with self.subTest(i=i):
                    self.assertFalse(a in g, "failed discarding of object by value in {}".format(name))

            # real object discarding test
            to_discard = int(no_insertions*0.1)  # delete 10%
            indices_discard = range(to_discard)
            with TimeCode("discarding {} items by name in {} ".format(to_discard, name)) as tc:
                for i, j in enumerate(indices_discard):
                    a = agents[j]
                    del agents[j]  # reflect the changes in the group
                    tc.start_cummulative()
                    g.discard(a.name)
                    tc.end_cummulative()
                    #with self.subTest(i=i):
                    self.assertFalse(a in g, "failed discarding of object by name in {}".format(name))

            # real object discarding test
            to_discard = int(no_insertions*0.1)  # delete 10%
            indices_discard = range(to_discard)
            with TimeCode("discarding {} items by index in {} ".format(to_discard, name)) as tc:
                for i, j in enumerate(indices_discard):
                    a = agents[j]
                    del agents[j]  # reflect the changes in the group
                    tc.start_cummulative()
                    g.discard(g[j])  # discard only accept name or object
                    tc.end_cummulative()
                    #with self.subTest(i=i):
                    self.assertFalse(a in g, "failed discarding of object by index in {}".format(name))

            with TimeCode("clearing {} items in {} ".format(len(agents), name)):
                g.clear()
            self.assertTrue(len(g) == 0, "failed to clear {}".format(name))
            print("")


def suite_alias():
    suite = unittest.TestSuite()
    suite.addTest(SpaceTestCase('test_hierarchy'))
    return suite


if __name__ == "__main__":
    unittest.main()
    # unittest.TextTestRunner(suite_alias())
