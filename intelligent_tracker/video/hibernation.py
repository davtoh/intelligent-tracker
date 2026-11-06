"""Deep capture stream hibernation controls for CPU conservation."""

import logging
import threading

logger = logging.getLogger(__name__)


class StreamHibernationMixin:
    """Capture worker hibernation pause/resume control mixin."""

    source: str
    _lock: threading.Lock
    _is_paused: bool
    _pause_event: threading.Event

    def pause(self) -> None:
        """Pause capture worker thread during stream hibernation to conserve CPU."""
        with self._lock:
            self._is_paused = True
            self._pause_event.clear()
            logger.debug("VideoSource '%s': Paused (hibernating).", self.source)

    def resume(self) -> None:
        """Resume capture worker thread immediately from hibernation."""
        with self._lock:
            self._is_paused = False
            self._pause_event.set()
            logger.debug("VideoSource '%s': Resumed from hibernation.", self.source)

    @property
    def is_paused(self) -> bool:
        """Returns True if the video capture is currently hibernated."""
        return self._is_paused


__all__ = ["StreamHibernationMixin"]

