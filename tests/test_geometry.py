#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# import built-in modules
import sys

# import third party modules
import unittest
from intelligent_tracker.geometry import line_intersection, intersect_analytical
from intelligent_tracker.array_utils import check_contours, convert
import numpy as np

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


class MyTestCase(unittest.TestCase):
    def setUp(self):
        "Hook method for setting up the test fixture before exercising it."

        self.cnta = [(2,7),(1,6),(1,4),(1,2),(2,0),(3,0),
                (5,0),(5,2),(5,3),(6,4),(6,6),(4,7)]
        self.cntb = [(7,5),(9,5),(10,4),(10,3),(9,2),(8,1),
                (6,1),(4,1),(2,2),(2,4),(3,5),(5,5)]
        self.cntab = [(6,5),(5,5),(3,5),(2,4),(2,2),(4,1),
                 (5,1),(5,2),(5,3),(6,4)]

    def tearDown(self):
        "Hook method for deconstructing the test fixture after testing it."
        pass

    def test_line_intersections(self):
        vertical = np.array([(5, 0), (5, 10)])
        horizontal = np.array([(0, 5), (10, 5)])

        self.assertEqual(line_intersection(vertical, horizontal), (5, 5))
        # move vertical to right, outside
        self.assertEqual(line_intersection(vertical + (6, 0), horizontal), None)
        # move vertical to left, outside
        self.assertEqual(line_intersection([(-1,0),(-1,10)],[(0,5),(10,5)]), None)
        # move horizontal up, outside
        self.assertEqual(line_intersection([(5,0),(5,10)],[(0,11),(10,11)]), None)
        # move horizontal down, outside
        self.assertEqual(line_intersection([(5,0),(5,10)],[(0,-1),(10,-1)]), None)

        # assert X
        self.assertEqual(line_intersection([(0,0),(10,10)],[(0,10),(10,0)]), (5, 5))
        # move -slope- to right, outside
        self.assertEqual(line_intersection([(0,0),(10,10)],[(11,10),(21,0)]), None)
        # move -slope- to left, outside
        self.assertEqual(line_intersection([(0,0),(10,10)],[(-11,10),(-1,0)]), None)
        # move +slope+ up, outside
        self.assertEqual(line_intersection([(0,11),(10,21)],[(0,10),(10,0)]), None)
        # move +slope+ down, outside
        self.assertEqual(line_intersection([(0,-11),(10,-1)],[(0,10),(10,0)]), None)

    def test_check_contours(self):

        ### test check function
        cntab = self.cntab
        self.assertTrue(check_contours([cntab], [cntab]))
        self.assertTrue(check_contours([cntab[::-1]], [cntab]))
        self.assertTrue(check_contours([convert(cntab, 3)], [cntab]))
        self.assertTrue(check_contours([convert(cntab[::-1], 4)], [cntab]))

    def test_contours(self):
        ### test contour intersections using analytical method
        #np.roll(vec, shift)
        cnt1 = [(8,8),(12,8),(12,12),(8,12),(8,9)]
        cnt2 = [(5,5),(10,5),(10,10),(5,10)]
        cnt3 = [(5,2),(5,5),(5,10),(10,10),(10,5),(14,5),
                (14,11),(11,11),(11,14),(16,14),(16,2)]
        cnt1 = convert(cnt1)
        cnt2 = convert(cnt2)
        cnt3 = convert(cnt3)
        contours = intersect_analytical([cnt1, cnt3])
        self.assertTrue(check_contours(contours, [[(8, 9), (8, 8), (10, 8), (10, 10), (8, 10)],
                                         [(12, 12), (11, 12), (11, 11), (12, 11)]]))
        contours = intersect_analytical([cnt1, cnt2])
        self.assertTrue(check_contours(contours, [[(8, 9), (8, 8), (10, 8), (10, 10), (8, 10)]]))
        contours = intersect_analytical([cnt2, cnt3])
        self.assertTrue(check_contours(contours, [[(5, 5), (10, 5), (10, 10), (5, 10)]]))

        cnta = self.cnta
        cntb = self.cntb
        cntab = self.cntab
        contours = intersect_analytical([convert(cnta), convert(cntb)])
        self.assertTrue(check_contours(contours, [cntab]))

        contours = intersect_analytical([convert(cntb), convert(cnta)])
        self.assertTrue(check_contours(contours, [cntab]))

        contours = intersect_analytical([convert(cnta, 3), convert(cntb, 7)])
        self.assertTrue(check_contours(contours, [cntab]))

        cnt_custom1 = [[(160, 402), (308, 257), (570, 162), (793, 272), (843, 555),
                        (800, 792), (531, 867), (223, 825), (86, 642)],
                       [(141, 172), (303, 325), (345, 500), (358, 677), (268, 882),
                        (101, 902), (20, 690), (41, 352)],
                       [(230.0, 555.0), (253.3, 490.0), (448.3, 427.5), (613.3, 490.0),
                        (613.3, 617.5), (533.3, 700.0), (388.3, 750.0), (275.0, 745.0),
                        (218.3, 630.0)]]
        cnt_custom1_i = [(275, 745), (218, 630), (230, 555), (253, 490), (336, 463),
                         (345, 500), (358, 677), (327, 747)]
        contours = intersect_analytical([convert(cnt) for cnt in cnt_custom1])
        self.assertTrue(check_contours(contours, [cnt_custom1_i]))


def suite_alias():
    suite = unittest.TestSuite()
    suite.addTest(MyTestCase('test_line_intersections'))
    suite.addTest(MyTestCase('test_check_contours'))
    suite.addTest(MyTestCase('test_contours'))
    return suite


if __name__ == "__main__":
    unittest.main()
    # unittest.TextTestRunner(suite_alias())
