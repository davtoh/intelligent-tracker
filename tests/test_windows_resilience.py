#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Unit Tests for Windows Asyncio IOCP Resilience.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

from dashboard.services.windows_resilience import (
    apply_windows_iocp_patch,
    TRANSIENT_WIN_SOCKET_ERRORS,
)


class TestWindowsResilience(unittest.TestCase):
    """Test suite for Windows IOCP Proactor socket resilience."""

    def test_transient_error_constants(self):
        """Ensure standard Windows client disconnect error codes are included."""
        self.assertIn(64, TRANSIENT_WIN_SOCKET_ERRORS)     # ERROR_NETNAME_DELETED
        self.assertIn(121, TRANSIENT_WIN_SOCKET_ERRORS)    # ERROR_SEM_TIMEOUT
        self.assertIn(1236, TRANSIENT_WIN_SOCKET_ERRORS)   # ERROR_CONNECTION_ABORTED
        self.assertIn(10054, TRANSIENT_WIN_SOCKET_ERRORS)  # WSAECONNRESET

    def test_apply_patch_idempotency(self):
        """Applying the patch multiple times should be safe and idempotent."""
        res1 = apply_windows_iocp_patch()
        res2 = apply_windows_iocp_patch()
        # Second invocation must safely return False (already patched)
        self.assertFalse(res2)


if __name__ == "__main__":
    unittest.main()

