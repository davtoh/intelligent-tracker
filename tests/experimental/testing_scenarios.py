import sys
sys.setrecursionlimit(1000000)

def trace_calls(frame, event, arg):
    # https://pymotw.com/2/sys/tracing.html
    if event != 'call':
        return
    co = frame.f_code
    func_name = co.co_name
    if func_name == 'write':
        # Ignore write() calls from print statements
        return
    func_line_no = frame.f_lineno
    func_filename = co.co_filename
    caller = frame.f_back
    caller_line_no = caller.f_lineno
    caller_filename = caller.f_code.co_filename
    print('Call to %s on line %s of %s from line %s of %s' % \
        (func_name, func_line_no, func_filename,
         caller_line_no, caller_filename))
    return

#sys.settrace(trace_calls)

# import build-in modules
import sys

# import third party modules
from intelligent_tracker.high_objects import Scene, World, Space
from intelligent_tracker.forms import EventFigure
import matplotlib.pyplot as plt
#import pympler.asizeof  # https://stackoverflow.com/a/1816648/5288758


def mem():
    # only linux
    import resource
    # https://stackoverflow.com/q/32167386/5288758
    print('Memory usage         : % 2.2f MB' % round(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024.0/1024.0, 1)
    )

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

# create world in scene
world = World(name="World")

# create scenes in world
newton1 = world.create_scene([None], name="Newton", framerate=30, resolution=(500, 500))
# tests
newton2 = world.scenes["Newton"]
assert newton1 is newton2
newton3 = world._space_get_item("scenes.Newton")
assert newton2 is newton3
newton4 = world.scenes[newton1]
assert newton4 is newton1
look = Space._space_get_from_hierarchy("Wo*")
assert world.name in look and look[world.name] is world
look2 = world._space_get_from_hierarchy("*")
#bergen = world.create_scene([None], name="Bergen", framerate=1)

# create detectors in world and assign them to the desired scenes
#world.create_detector("colordetector", [148, 148, 0], [196, 255, 255], name="red")
#world.create_detector("colordetector", [56, 73, 135], [86, 119, 204], name="green")
world.create_detector("FaceDetector")
# see world
world.show(throw=False)
#world.close("Newton")
#world.show()
#world.close()
#scene = Scene([None])
#scene.show()
#scene.resolution = (300,200)
#scene.framerate = 1
#scene.close()
#scene.show()
# only leave if all scenes windows are closed
world.block(close=True)

import gc
import pprint

class Graph(object):
    def __init__(self, name):
        self.name = name
        self.next = None

    def set_next(self, next):
        print('Linking nodes %s.next = %s' % (self, next))
        self.next = next

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, self.name)

    def __del__(self):
        print('%s.__del__()' % self)


# Construct two graph cycles
one = Graph('one')
two = Graph('two')
three = Graph('three')
one.set_next(two)
two.set_next(three)
three.set_next(one)

# Remove references to the graph nodes in this module's namespace
one = two = three = None

# Collecting now keeps the objects as uncollectable
print("")
print('Collecting...')
n = gc.collect()
print('Unreachable objects:', n)
print('Remaining Garbage:', end="")
pprint.pprint(gc.garbage)

REFERRERS_TO_IGNORE = [locals(), globals(), gc.garbage]


def find_referring_graphs(obj):
    #print('Looking for references to %s' % repr(obj))
    referrers = (r for r in gc.get_referrers(obj)
                 if r not in REFERRERS_TO_IGNORE)
    for ref in referrers:
        if isinstance(ref, Graph):
            # A graph node
            yield ref
        elif isinstance(ref, dict):
            # An instance or other namespace dictionary
            for parent in find_referring_graphs(ref):
                yield parent


# Look for objects that refer to the objects that remain in
# gc.garbage.
print("")
print('Clearing referrers:')
for obj in gc.garbage:
    for ref in find_referring_graphs(obj):
        ref.set_next(None)
        del ref  # remove local reference so the node can be deleted
    del obj  # remove local reference so the node can be deleted

# Clear references held by gc.garbage
print("")
print('Clearing gc.garbage:')
del gc.garbage[:]

# Everything should have been freed this time
print("")
print('Collecting...')

n = gc.collect()
print('Unreachable objects:', n)
print('Remaining Garbage:', end="")
pprint.pprint(gc.garbage)