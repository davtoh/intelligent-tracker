#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Central Graceful Shutdown & Cancellation Handler.

Provides:
- Immediate shutdown signal interception (SIGINT, SIGTERM, SIGBREAK) broadcasting
  rapid stop events to active camera streams and streaming responses.
- Concurrent non-blocking pool teardown via asyncio.to_thread.
- Fail-safe watchdog timer preventing deadlocks in kernel-space OS drivers.
- ASGI cancellation middleware suppressing benign asyncio.CancelledError exceptions
  during server termination or client connection aborts.
"""

import asyncio
import logging
import os
import signal
import sys
import threading
import time
from typing import Callable

logger = logging.getLogger("intelligent_tracker.shutdown_handler")

_HANDLERS_INSTALLED = False
_WATCHDOG_STARTED = False
_WATCHDOG_LOCK = threading.Lock()


def get_console_logger() -> logging.Logger:
    """Resolve an active console-bound logger (prioritizing uvicorn.error)."""
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger.handlers:
        return uvicorn_logger
    if uvicorn_logger.parent and uvicorn_logger.parent.handlers:
        return uvicorn_logger.parent
    if logger.handlers:
        return logger
    root_log = logging.getLogger()
    if root_log.handlers:
        return root_log
    return logger


def is_test_environment() -> bool:
    """Return True if running inside an automated test suite runner."""
    main_mod = sys.modules.get("__main__")
    main_file = getattr(main_mod, "__file__", "") or ""
    return (
        os.environ.get("TESTING") == "1"
        or any("unittest" in str(arg).lower() or "pytest" in str(arg).lower() for arg in sys.argv)
        or "unittest" in main_file.lower()
        or "pytest" in main_file.lower()
    )


def start_watchdog_guard(timeout: float = 4.0) -> None:
    """
    Start a background watchdog daemon ensuring the process exits even if
    an external C/C++ driver (DirectShow/MSMF/V4L2) deadlocks in kernel space.
    """
    global _WATCHDOG_STARTED
    with _WATCHDOG_LOCK:
        if _WATCHDOG_STARTED:
            return
        _WATCHDOG_STARTED = True

    def _watchdog_worker():
        time.sleep(timeout)
        con_log = get_console_logger()
        con_log.warning(
            "Graceful shutdown watchdog timeout (%.1fs) reached; forcing clean process exit.",
            timeout,
        )
        if not is_test_environment():
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass
            os._exit(0)

    t = threading.Thread(target=_watchdog_worker, name="ShutdownWatchdogGuard", daemon=True)
    t.start()


def broadcast_shutdown() -> None:
    """
    Immediately broadcast shutdown signal across all active subsystems,
    stopping video sources and client streams without waiting for joins.
    """
    from dashboard.dependencies import (
        get_camera_pool,
        get_active_stream_manager,
        set_shutting_down,
    )

    set_shutting_down(True)

    pool = get_camera_pool()
    if pool and hasattr(pool, "signal_stop_all"):
        pool.signal_stop_all()
    else:
        sm = get_active_stream_manager()
        if sm and hasattr(sm, "signal_stop"):
            sm.signal_stop()

    start_watchdog_guard(timeout=4.0)


def install_shutdown_handlers() -> None:
    """
    Wrap operating system interrupt and termination signals to trigger
    immediate stream cancellation upon the first CTRL+C or SIGTERM event.
    """
    global _HANDLERS_INSTALLED
    if _HANDLERS_INSTALLED:
        return

    target_signals = ["SIGINT", "SIGTERM"]
    if sys.platform == "win32":
        target_signals.append("SIGBREAK")

    for sig_name in target_signals:
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            prev_handler = signal.getsignal(sig)
            if callable(prev_handler):
                def _create_handler(orig_handler: Callable, name: str) -> Callable:
                    def _sig_handler(signum, frame):
                        con_log = get_console_logger()
                        con_log.info(
                            "Intercepted %s: broadcasting fast shutdown to all camera streams...",
                            name,
                        )
                        broadcast_shutdown()
                        orig_handler(signum, frame)
                    return _sig_handler

                signal.signal(sig, _create_handler(prev_handler, sig_name))
        except (ValueError, OSError) as exc:
            logger.debug("Could not attach signal handler for %s: %s", sig_name, exc)

    _HANDLERS_INSTALLED = True
    logger.debug("Installed graceful shutdown signal hooks.")


async def async_shutdown_pool(camera_pool, timeout: float = 3.0) -> None:
    """
    Asynchronously terminate all camera streams in parallel off the main thread,
    preventing event loop starvation and blocking.
    """
    if camera_pool is None:
        return

    broadcast_shutdown()
    con_log = get_console_logger()
    start_t = time.time()

    try:
        await asyncio.wait_for(
            asyncio.to_thread(camera_pool.stop_all, parallel=True),
            timeout=timeout,
        )
        elapsed = time.time() - start_t
        con_log.info("Intelligent Tracker CameraPool stopped cleanly in %.2fs.", elapsed)
    except asyncio.TimeoutError:
        con_log.warning(
            "CameraPool parallel stop timed out after %.1fs; continuing shutdown...",
            timeout,
        )
    except Exception as exc:
        con_log.debug("Exception during async pool shutdown: %s", exc)


class GracefulCancellationMiddleware:
    """
    ASGI middleware ensuring asyncio.CancelledError from aborted streaming connections
    or server shutdown does not bubble up as an unhandled ASGI 500 or traceback.
    """

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        try:
            await self.app(scope, receive, send)
        except (asyncio.CancelledError, GeneratorExit):
            if scope.get("type") in ("http", "websocket"):
                return
            raise
