#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# import built-in modules
import sys

# import third party modules

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
import numpy as np
from intelligent_tracker.forms import EventFigure


class MyTestCase(unittest.TestCase):
    def setUp(self):
        "Hook method for setting up the test fixture before exercising it."
        pass

    def tearDown(self):
        "Hook method for deconstructing the test fixture after testing it."
        pass

    def test_basic(self):
        class Test(EventFigure):

            def update_func(self, *args):
                if args[0] > 10:
                    self.close()
                print(args)
                global x, y
                x += np.pi / 15.
                y += np.pi / 20.
                self.artist.set_array(f(x, y))
                return self.artist,

            def key_press_event(self, event):
                print('press', event.key)
                sys.stdout.flush()
                if event.key == 'q':
                    self.close()
                    # fig.canvas.draw()

        def f(x, y):
            return np.sin(x) + np.cos(y)

        x = np.linspace(0, 2 * np.pi, 120)
        y = np.linspace(0, 2 * np.pi, 100).reshape(-1, 1)
        fig = Test(f(x, y))

        iterations = 0
        while not fig.closed():
            x += np.pi / 15.
            y += np.pi / 20.
            fig.update(f(x, y), 0.01)
            # sleep(0.5)
            # plt.pause(1)
            # fig.show()
            iterations += 1
            if iterations >= 10:
                fig.close()
                break


def suite_alias():
    suite = unittest.TestSuite()
    suite.addTest(MyTestCase('test_basic'))
    return suite


if __name__ == "__main__":
    unittest.main()
    # unittest.TextTestRunner(suite_alias())
