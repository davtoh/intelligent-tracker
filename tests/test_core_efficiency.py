#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Group and CompleteGroup performance, memory scaling, and execution efficiency.

Tests:
1. Memory allocation and footprint estimation for large agent collections.
2. Micro-benchmarks for index, value, and name lookups.
3. Batch insertions, mutations, reversals, discards, and clears.
"""

import os
import sys
import time
import unittest
from contextlib import contextmanager

try:
    import resource
except ImportError:
    resource = None
try:
    import psutil
except ImportError:
    psutil = None

from intelligent_tracker.core import Agent, Group, CompleteGroup


def bytes2MB(b):
    """Convert bytes to megabytes."""
    return b / 1024.0 / 1024.0


def mem(print_flag=True):
    """Report current process memory usage in MB."""
    if resource is not None:
        usage = round(bytes2MB(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss), 1)
    elif psutil is not None:
        usage = round(bytes2MB(psutil.Process(os.getpid()).memory_info().rss), 1)
    else:
        usage = 0.0
    if print_flag:
        print('Memory usage         : % 2.2f MB' % usage)
    return usage


def memory_usage_psutil():
    """Return memory percent and resident memory usage in MB."""
    if psutil is not None:
        process = psutil.Process(os.getpid())
        per = process.memory_percent()
        mem_mb = bytes2MB(process.memory_full_info().rss)
    else:
        per, mem_mb = 0.0, 0.0
    return per, mem_mb


class TimeCode:
    """Execution timer context manager replacing legacy RRtoolbox TimeCode."""

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
    """Helper assertions for unittest test cases."""

    @contextmanager
    def assertNotRaises(self, Exception, msg=None):
        try:
            yield
        except Exception:
            msg = self._formatMessage(msg, '{} raised'.format(Exception))
            raise self.failureException(msg)


class GroupEfficiencyTestCase(unittest.TestCase, CustomAssertions):
    """Performance and memory benchmark test case comparing Group and CompleteGroup."""

    def setUp(self):
        self.groups = [Group(), CompleteGroup()]

    def tearDown(self):
        self.groups.clear()

    def _benchmark_name_mutation(self, g, name, agents, indices, a_rev):
        """Benchmark name mutation and verify retrieval post-rename."""
        with TimeCode("changing agent name {} times when {} is used: ".format(len(indices), name)):
            for a in a_rev:
                a.name = a.name + "_changed"

        for j, a in zip(indices, a_rev):
            self.assertIs(a, g[a.name], "failed retrieval by name when name changed in {}".format(name))
            self.assertIs(agents[j], g[j], "failed retrieval by index when name changed in {}".format(name))
            self.assertTrue(j == g.index(a), "failed retrieval of index when name changed in {}".format(name))

    def _benchmark_retrievals(self, g, name, agents, indices, a_rev):
        """Benchmark index, value, name lookup, and mutations."""
        printed = []
        with TimeCode("getting agent by index {} times in {}: ".format(len(indices), name), printfunc=printed.append) as tc:
            for i in indices:
                tc.start_cummulative()
                _ = g[i]
                tc.end_cummulative()
        printed[-1] = printed[-1].strip() + "\n"
        for p in printed:
            print(p, end="")

        for j, a in zip(indices, a_rev):
            self.assertIs(a, g[j], "failed retrieval by index in {}".format(name))
            self.assertTrue(j == g.index(a), "failed retrieval of index in {}".format(name))

        with TimeCode("getting agent by value {} times in {}: ".format(len(indices), name)):
            for a in a_rev:
                _ = g[a]
        for a in a_rev:
            self.assertIs(a, g[a], "failed retrieval by object in {}".format(name))

        with TimeCode("getting agent by name {} times in {}: ".format(len(indices), name)):
            for a in a_rev:
                _ = g[a.name]
        for a in a_rev:
            self.assertIs(a, g[a.name], "failed retrieval by name in {}".format(name))

        with TimeCode("iterating {} items in {} ".format(len(agents), name)):
            for _ in g:
                pass

        self._benchmark_name_mutation(g, name, agents, indices, a_rev)

    def _benchmark_discards(self, g, name, agents, no_insertions):
        """Benchmark sequential discard by value, name, and index."""
        with TimeCode("reversing {} items in {} ".format(len(agents), name)):
            g.reverse()
        agents.reverse()
        for i, a in enumerate(g):
            self.assertIs(a, agents[i], "failed reverse comparison by iteration in {}".format(name))
            self.assertTrue(g.index(a) == i, "failed reverse comparison by index in {}".format(name))

        to_discard = int(no_insertions * 0.1)
        with TimeCode("discarding {} items by value in {} ".format(to_discard, name)) as tc:
            for j in range(to_discard):
                a = agents[j]
                del agents[j]
                tc.start_cummulative()
                g.discard(a)
                tc.end_cummulative()
                self.assertFalse(a in g, "failed discarding of object by value in {}".format(name))

        with TimeCode("discarding {} items by name in {} ".format(to_discard, name)) as tc:
            for j in range(to_discard):
                a = agents[j]
                del agents[j]
                tc.start_cummulative()
                g.discard(a.name)
                tc.end_cummulative()
                self.assertFalse(a in g, "failed discarding of object by name in {}".format(name))

        with TimeCode("discarding {} items by index in {} ".format(to_discard, name)) as tc:
            for j in range(to_discard):
                del agents[j]
                tc.start_cummulative()
                g.discard(g[j])
                tc.end_cummulative()
                self.assertFalse(a in g, "failed discarding of object by index in {}".format(name))

        with TimeCode("clearing {} items in {} ".format(len(agents), name)):
            g.clear()
        self.assertTrue(len(g) == 0, "failed to clear {}".format(name))
        print("")

    def test_compare(self):
        """Execute performance and scaling comparisons across Group implementations."""
        no_insertions = 1000
        agents_base = [Agent() for _ in range(no_insertions)]
        for g in self.groups:
            agents = agents_base.copy()
            name = g.__class__.__name__
            with TimeCode("updating {} with {} items: ".format(name, len(agents))):
                g.update(agents, as_parent=True, as_contained=True)
            my_size = bytes2MB(asizeof(g))
            percentage, used = memory_usage_psutil()
            print("{} size {:.2f} MB, program {:.2f} MB, {:.2f}% of total memory".format(
                name, my_size, used, percentage
            ))

            step = 10
            indices = list(range(0, no_insertions, step))
            a_rev = [agents[i] for i in indices]

            self._benchmark_retrievals(g, name, agents, indices, a_rev)
            self._benchmark_discards(g, name, agents, no_insertions)


if __name__ == "__main__":
    unittest.main()
