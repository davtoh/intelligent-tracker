#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Convenience CLI shortcut for Intelligent Tracker camera diagnostics and resource management.
Usage:
    python scripts/camera_manager.py --status
    python scripts/camera_manager.py --release
    python scripts/camera_manager.py --test 1
"""

import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from intelligent_tracker.camera_tool import main

if __name__ == "__main__":
    main()

