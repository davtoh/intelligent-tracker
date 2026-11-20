"""Logging handler that forwards ERROR+ logs to the diagnostic trace bridge."""

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from dashboard.services.diagnostic_bridge import capture_runtime_exception

_ALLOWED_PREFIXES = ("intelligent_tracker", "dashboard")


class DiagnosticLogHandler(logging.Handler):
    """Capture ERROR+ logs from tracker/dashboard loggers into .diagnostics/traces/."""

    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        cooldown_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(level=logging.ERROR)
        self._workspace_root = workspace_root
        self._cooldown_s = max(0.0, float(cooldown_s))
        self._clock = clock
        self._lock = threading.Lock()
        self._last_seen: dict[tuple[str, str], float] = {}

    @staticmethod
    def _is_target_logger(logger_name: str) -> bool:
        return any(
            logger_name == prefix or logger_name.startswith(f"{prefix}.")
            for prefix in _ALLOWED_PREFIXES
        )

    def _should_record(self, key: tuple[str, str]) -> bool:
        now = self._clock()
        with self._lock:
            prev = self._last_seen.get(key)
            if prev is not None and (now - prev) < self._cooldown_s:
                return False
            self._last_seen[key] = now
            return True

    def emit(self, record: logging.LogRecord) -> None:
        """Record deduplicated ERROR+ log events without ever raising."""
        try:
            if record.levelno < logging.ERROR:
                return
            if not self._is_target_logger(record.name):
                return
            msg = record.getMessage()
            key = (record.name, msg[:80])
            if not self._should_record(key):
                return
            exc = (
                record.exc_info[1]
                if record.exc_info and isinstance(record.exc_info[1], BaseException)
                else RuntimeError(f"[{record.levelname}] {record.name}: {msg}")
            )
            context = {
                "logger": record.name,
                "level": record.levelname,
                "pathname": record.pathname,
                "lineno": record.lineno,
            }
            capture_runtime_exception(
                exc,
                context=context,
                workspace_root=self._workspace_root,
            )
        except Exception:
            pass


def install_diagnostic_log_handler(
    workspace_root: Optional[Path] = None,
    cooldown_s: float = 60.0,
) -> DiagnosticLogHandler:
    """Attach a DiagnosticLogHandler to the root logger and return it."""
    handler = DiagnosticLogHandler(workspace_root=workspace_root, cooldown_s=cooldown_s)
    logging.getLogger().addHandler(handler)
    return handler


def remove_diagnostic_log_handler(handler: Optional[DiagnosticLogHandler]) -> None:
    """Detach a previously installed DiagnosticLogHandler from the root logger."""
    if handler is not None:
        logging.getLogger().removeHandler(handler)
