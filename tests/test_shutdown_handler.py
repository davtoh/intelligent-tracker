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
        with patch("dashboard.dependencies.set_shutting_down") as mock_set_shutting_down:
            install_shutdown_handlers()
            handler = signal.getsignal(signal.SIGINT)
            self.assertTrue(callable(handler))

            # Simulate signal trigger (calls previous handler, which raises KeyboardInterrupt if default)
            try:
                handler(signal.SIGINT, None)
            except KeyboardInterrupt:
                pass

            mock_set_shutting_down.assert_called_with(True)


if __name__ == "__main__":
    unittest.main()
