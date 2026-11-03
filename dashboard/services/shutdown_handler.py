#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Central Graceful Shutdown & Cancellation Handler.

Provides:
- Immediate shutdown signal interception (SIGINT, SIGTERM, SIGBREAK) to unblock
  active streaming responses before Uvicorn enters its blocking connection-wait loop.
- ASGI cancellation middleware suppressing benign asyncio.CancelledError exceptions
  during server termination or client connection aborts.
"""

import asyncio
import logging
import signal
import sys
from typing import Callable, Optional

logger = logging.getLogger("intelligent_tracker.shutdown_handler")

_HANDLERS_INSTALLED = False


def install_shutdown_handlers() -> None:
    """
    Wrap operating system interrupt and termination signals to trigger
    immediate stream cancellation upon the first CTRL+C or SIGTERM event.
    """
    global _HANDLERS_INSTALLED
    if _HANDLERS_INSTALLED:
        return

    from dashboard.dependencies import set_shutting_down

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
                        logger.info("Intercepted %s, signaling active streams to disconnect...", name)
                        set_shutting_down(True)
                        orig_handler(signum, frame)
                    return _sig_handler

                signal.signal(sig, _create_handler(prev_handler, sig_name))
        except (ValueError, OSError) as exc:
            logger.debug("Could not attach signal handler for %s: %s", sig_name, exc)

    _HANDLERS_INSTALLED = True
    logger.debug("Installed graceful shutdown signal hooks.")


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

