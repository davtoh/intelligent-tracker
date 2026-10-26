#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# import built-in modules
import sys

# import third party modules

# special variables
# __all__ = []
__author__ = "David Toro"
# __copyright__ = "Copyright 2017, The <name> Project"
# __credits__ = [""]
__license__ = "GPL"
__version__ = "0.1.2"
__maintainer__ = "David Toro"
__email__ = "davsamirtor@gmail.com"
__status__ = "Pre-release"


class ContextSupport:
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()