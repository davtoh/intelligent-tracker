"""Unit tests for DiagnosticLogHandler deduplication, filtering, and safety."""

import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.services.diagnostic_log_handler import (
    DiagnosticLogHandler,
    install_diagnostic_log_handler,
    remove_diagnostic_log_handler,
)


class _FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class TestDiagnosticLogHandler(unittest.TestCase):
    """Verify ERROR+ log capture, logger filtering, 60s dedup, and non-raising emit."""

    def test_filters_non_target_loggers_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = DiagnosticLogHandler(workspace_root=Path(tmpdir))
            with patch("dashboard.services.diagnostic_log_handler.capture_runtime_exception") as mock_cap:
                warn_rec = logging.LogRecord("intelligent_tracker.cam", logging.WARNING, __file__, 10, "warn", (), None)
                third_party = logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 11, "err", (), None)
                handler.emit(warn_rec)
                handler.emit(third_party)
                mock_cap.assert_not_called()

    def test_deduplicates_within_cooldown_and_allows_after(self) -> None:
        clock = _FakeClock(100.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = DiagnosticLogHandler(workspace_root=Path(tmpdir), cooldown_s=60.0, clock=clock)
            with patch("dashboard.services.diagnostic_log_handler.capture_runtime_exception") as mock_cap:
                rec = logging.LogRecord("intelligent_tracker.video", logging.ERROR, __file__, 20, "VideoSource '2': reconnect exhausted", (), None)
                handler.emit(rec)
                clock.now = 120.0
                handler.emit(rec)
                self.assertEqual(mock_cap.call_count, 1)
                clock.now = 161.0
                handler.emit(rec)
                self.assertEqual(mock_cap.call_count, 2)

    def test_emit_never_raises_when_bridge_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = DiagnosticLogHandler(workspace_root=Path(tmpdir))
            with patch("dashboard.services.diagnostic_log_handler.capture_runtime_exception", side_effect=OSError("disk full")):
                rec = logging.LogRecord("dashboard.stream", logging.ERROR, __file__, 30, "boom", (), None)
                handler.emit(rec)

    def test_install_and_remove_handler_on_root_logger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = install_diagnostic_log_handler(workspace_root=Path(tmpdir))
            self.addCleanup(remove_diagnostic_log_handler, handler)
            self.assertIn(handler, logging.getLogger().handlers)
            remove_diagnostic_log_handler(handler)
            self.assertNotIn(handler, logging.getLogger().handlers)
