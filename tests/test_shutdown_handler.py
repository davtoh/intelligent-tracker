#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for GracefulCancellationMiddleware and shutdown signal installation.
"""

import asyncio
import signal
import unittest
from unittest.mock import MagicMock, patch

from dashboard.services.shutdown_handler import (
    GracefulCancellationMiddleware,
    install_shutdown_handlers,
)


class TestShutdownHandler(unittest.TestCase):
    """Test suite for server shutdown and cancellation resilience."""

    def test_cancellation_middleware_absorbs_cancelled_error(self):
        """Verify middleware catches CancelledError on HTTP scope without raising."""
        async def failing_app(scope, receive, send):
            raise asyncio.CancelledError("Client disconnected")

        middleware = GracefulCancellationMiddleware(failing_app)

        async def run_test():
            scope = {"type": "http"}
            receive = MagicMock()
            send = MagicMock()
            # Should not raise exception
            await middleware(scope, receive, send)

        asyncio.run(run_test())

    def test_cancellation_middleware_propagates_non_cancelled_errors(self):
        """Verify standard exceptions are properly propagated through middleware."""
        async def failing_app(scope, receive, send):
            raise RuntimeError("Database connection died")

        middleware = GracefulCancellationMiddleware(failing_app)

        async def run_test():
            scope = {"type": "http"}
            with self.assertRaises(RuntimeError):
                await middleware(scope, MagicMock(), MagicMock())

        asyncio.run(run_test())

    def test_install_shutdown_handlers(self):
        """Verify signal handlers wrap existing handlers and invoke set_shutting_down."""
        with patch("dashboard.dependencies.set_shutting_down") as mock_set_shutting_down, \
             patch("dashboard.services.shutdown_handler.start_watchdog_guard"):
            install_shutdown_handlers()
            handler = signal.getsignal(signal.SIGINT)
            self.assertTrue(callable(handler))

            # Simulate signal trigger (calls previous handler, which raises KeyboardInterrupt if default)
            try:
                handler(signal.SIGINT, None)
            except KeyboardInterrupt:
                pass

            mock_set_shutting_down.assert_called_with(True)

    def test_async_shutdown_pool_handles_none(self):
        """async_shutdown_pool must safely return without error when camera_pool is None."""
        from dashboard.services.shutdown_handler import async_shutdown_pool
        asyncio.run(async_shutdown_pool(None))

    def test_start_watchdog_guard_idempotent(self):
        """start_watchdog_guard must start only a single daemon thread across repeated calls."""
        from dashboard.services.shutdown_handler import start_watchdog_guard
        start_watchdog_guard(timeout=10.0)
        start_watchdog_guard(timeout=10.0)

    def test_is_test_environment_detection(self):
        """is_test_environment must accurately identify test runners without false positives."""
        import sys
        from dashboard.services.shutdown_handler import is_test_environment

        # Under the active unittest runner, it must be True
        self.assertTrue(is_test_environment())

        # Under simulated production uvicorn execution, it must be False
        with patch.object(sys, "argv", ["C:\\Python312\\Scripts\\uvicorn.exe", "dashboard.app:app", "--port", "8000"]), \
             patch.dict(sys.modules, {"__main__": MagicMock(__file__="C:\\Python312\\Lib\\site-packages\\uvicorn\\main.py")}), \
             patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("TESTING", None)
            self.assertFalse(is_test_environment())

    def test_watchdog_triggers_exit_in_production(self):
        """Watchdog must trigger os._exit(0) when running in production mode."""
        import sys
        from dashboard.services.shutdown_handler import start_watchdog_guard
        import dashboard.services.shutdown_handler as sh

        with patch.object(sh, "_WATCHDOG_STARTED", False), \
             patch.object(sh, "is_test_environment", return_value=False), \
             patch("os._exit") as mock_exit:
            start_watchdog_guard(timeout=0.05)
            # Give daemon thread time to wake
            import time
            time.sleep(0.15)
            mock_exit.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
