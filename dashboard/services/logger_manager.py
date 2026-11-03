#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Central Log Manager & Deduplication Service.

Provides:
- Deduplicated logging to suppress repetitive error/warning flood in high-frequency loops.
- Rate-limited and state-aware logging (log-once until state changes or reset).
- Thread-safe state tracking per domain/key.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("intelligent_tracker.log_manager")


class DeduplicatingLogger:
    """
    Thread-safe logger utility preventing log spam in high-frequency loops.
    Only logs a message if the key/message has changed, or if a throttle period has elapsed.
    """
    _instance: Optional["DeduplicatingLogger"] = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs) -> "DeduplicatingLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._last_logs: Dict[str, Tuple[str, float]] = {}
        self._initialized = True

    def log_once(
        self,
        level: int,
        key: str,
        msg: str,
        *args: Any,
        target_logger: Optional[logging.Logger] = None,
        min_interval_sec: Optional[float] = None,
    ) -> bool:
        """
        Emit a log message only if (a) the formatted message differs from the previous
        message logged for `key`, or (b) `min_interval_sec` has elapsed since the last log.

        Returns:
            bool: True if the log was emitted, False if suppressed as a duplicate.
        """
        with self._lock:
            now = time.time()
            try:
                formatted = msg % args if args else msg
            except Exception:
                formatted = str(msg)

            last_entry = self._last_logs.get(key)
            if last_entry is not None:
                last_msg, last_time = last_entry
                if last_msg == formatted:
                    if min_interval_sec is None or (now - last_time) < min_interval_sec:
                        return False

            self._last_logs[key] = (formatted, now)
            log_target = target_logger or logger
            log_target.log(level, msg, *args)
            return True

    def reset(self, key: Optional[str] = None) -> None:
        """Clear recorded log state for a specific key or all keys."""
        with self._lock:
            if key is None:
                self._last_logs.clear()
            else:
                self._last_logs.pop(key, None)

    def warning_once(
        self,
        key: str,
        msg: str,
        *args: Any,
        target_logger: Optional[logging.Logger] = None,
        min_interval_sec: Optional[float] = None,
    ) -> bool:
        """Emit a WARNING log once until message changes or interval expires."""
        return self.log_once(
            logging.WARNING, key, msg, *args, target_logger=target_logger, min_interval_sec=min_interval_sec
        )

    def error_once(
        self,
        key: str,
        msg: str,
        *args: Any,
        target_logger: Optional[logging.Logger] = None,
        min_interval_sec: Optional[float] = None,
    ) -> bool:
        """Emit an ERROR log once until message changes or interval expires."""
        return self.log_once(
            logging.ERROR, key, msg, *args, target_logger=target_logger, min_interval_sec=min_interval_sec
        )

    def info_once(
        self,
        key: str,
        msg: str,
        *args: Any,
        target_logger: Optional[logging.Logger] = None,
        min_interval_sec: Optional[float] = None,
    ) -> bool:
        """Emit an INFO log once until message changes or interval expires."""
        return self.log_once(
            logging.INFO, key, msg, *args, target_logger=target_logger, min_interval_sec=min_interval_sec
        )

