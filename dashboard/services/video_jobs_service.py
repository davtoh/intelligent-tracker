import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class JobType(str, Enum):
    TRANSCODE = "transcode"
    ANALYTICS = "analytics"


@dataclass
class VideoJob:
    """Represents the lifecycle state, progress, and metrics of an async video task."""
    job_id: str
    job_type: str
    filename: str
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    stage: str = "queued"
    metrics: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value if isinstance(self.status, JobStatus) else str(self.status)
        return data


class VideoJobManager:
    """
    Thread-safe ledger and execution coordinator for offline video processing jobs.
    Enforces per-video mutual exclusion, system-wide concurrency limits,
    and responsive, interruptible cancellation.
    """

    def __init__(self, max_concurrent: int = 2):
        self._max_concurrent = max_concurrent
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._lock = threading.Lock()
        self._jobs: Dict[str, VideoJob] = {}
        self._stop_events: Dict[str, threading.Event] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._is_shutdown = False

    def submit_job(
        self,
        job_type: str,
        filename: str,
        runner_fn: Callable[[VideoJob, threading.Event, Callable[[Dict[str, Any]], None]], Dict[str, Any]],
        initial_metrics: Optional[Dict[str, Any]] = None,
    ) -> VideoJob:
        """
        Submit a new video job. Raises ValueError if a job is already active for this video file.
        """
        safe_name = os.path.basename(filename)
        with self._lock:
            if self._is_shutdown:
                raise RuntimeError("VideoJobManager is shut down")

            # Check per-video mutual exclusion
            active = self._get_active_job_for_file_unlocked(safe_name)
            if active is not None:
                raise ValueError(f"Job '{active.job_id}' is already active for video '{safe_name}'")

            job_id = f"job_{uuid.uuid4().hex[:12]}"
            job = VideoJob(
                job_id=job_id,
                job_type=job_type,
                filename=safe_name,
                metrics=initial_metrics or {},
            )
            stop_event = threading.Event()
            self._jobs[job_id] = job
            self._stop_events[job_id] = stop_event
            self._prune_history_unlocked()

        worker_thread = threading.Thread(
            target=self._execute_job,
            args=(job_id, runner_fn),
            daemon=True,
            name=f"VideoWorker-{job_id}",
        )
        with self._lock:
            self._threads[job_id] = worker_thread

        worker_thread.start()
        return job

    def _execute_job(
        self,
        job_id: str,
        runner_fn: Callable[[VideoJob, threading.Event, Callable[[Dict[str, Any]], None]], Dict[str, Any]],
    ) -> None:
        """Internal worker wrapper executing outside the ledger lock."""
        with self._lock:
            job = self._jobs.get(job_id)
            stop_event = self._stop_events.get(job_id)
        if not job or not stop_event:
            return

        # Acquire concurrency throttle semaphore with responsive cancellation
        acquired = False
        while not stop_event.is_set():
            with self._lock:
                if self._is_shutdown:
                    break
            if self._semaphore.acquire(timeout=0.1):
                acquired = True
                break

        if not acquired:
            with self._lock:
                job.status = JobStatus.CANCELLED
                job.stage = "cancelled_before_start"
                job.completed_at = time.time()
            return

        try:
            with self._lock:
                if stop_event.is_set():
                    job.status = JobStatus.CANCELLED
                    job.stage = "cancelled_before_start"
                    job.completed_at = time.time()
                    return
                job.status = JobStatus.RUNNING
                job.started_at = time.time()
                job.stage = "processing"

            def progress_callback(update: Dict[str, Any]) -> None:
                with self._lock:
                    if "percent" in update:
                        job.progress = min(100.0, max(0.0, float(update["percent"])))
                    if "stage" in update:
                        job.stage = str(update["stage"])
                    job.metrics.update(update)

            # Execute work outside of lock
            result = runner_fn(job, stop_event, progress_callback)

            with self._lock:
                if stop_event.is_set():
                    job.status = JobStatus.CANCELLED
                    job.stage = "cancelled"
                else:
                    job.status = JobStatus.COMPLETED
                    job.progress = 100.0
                    job.stage = "completed"
                    job.result = result
                job.completed_at = time.time()

        except Exception as e:
            logger.error("Job %s execution failed: %s", job_id, e, exc_info=True)
            with self._lock:
                if stop_event.is_set():
                    job.status = JobStatus.CANCELLED
                    job.stage = "cancelled"
                else:
                    job.status = JobStatus.FAILED
                    job.stage = "failed"
                    job.error = str(e)
                job.completed_at = time.time()
        finally:
            self._semaphore.release()

    def get_job(self, job_id: str) -> Optional[VideoJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def _get_active_job_for_file_unlocked(self, filename: str) -> Optional[VideoJob]:
        safe_name = os.path.basename(filename)
        for job in self._jobs.values():
            if job.filename == safe_name and job.status in (JobStatus.PENDING, JobStatus.RUNNING):
                return job
        return None

    def get_active_job_for_file(self, filename: str) -> Optional[VideoJob]:
        with self._lock:
            return self._get_active_job_for_file_unlocked(filename)

    def list_jobs(self, filename: Optional[str] = None, active_only: bool = False) -> List[VideoJob]:
        with self._lock:
            safe_name = os.path.basename(filename) if filename else None
            results = []
            for job in self._jobs.values():
                if safe_name and job.filename != safe_name:
                    continue
                if active_only and job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                    continue
                results.append(job)
            return sorted(results, key=lambda j: j.created_at, reverse=True)

    def cancel_job(self, job_id: str, wait_timeout: float = 2.0) -> bool:
        """Signals cancellation to an active job and optionally waits for worker thread exit."""
        with self._lock:
            job = self._jobs.get(job_id)
            stop_event = self._stop_events.get(job_id)
            thread = self._threads.get(job_id)
            if not job or not stop_event:
                return False
            if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                return False
            stop_event.set()
            job.stage = "cancelling"

        # Wait outside lock for worker thread to exit and release handles
        if wait_timeout > 0 and thread and thread.is_alive():
            thread.join(timeout=wait_timeout)
        return True

    def cancel_active_job_for_file(self, filename: str, wait_timeout: float = 2.0) -> bool:
        with self._lock:
            job = self._get_active_job_for_file_unlocked(filename)
            if not job:
                return False
            job_id = job.job_id
        return self.cancel_job(job_id, wait_timeout=wait_timeout)

    def _prune_history_unlocked(self, max_history: int = 100) -> None:
        """Removes old completed or failed jobs if capacity exceeded."""
        inactive = [j for j in self._jobs.values() if j.status in (JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED)]
        if len(inactive) > max_history:
            inactive.sort(key=lambda j: j.completed_at or j.created_at)
            to_remove = inactive[: len(inactive) - max_history]
            for j in to_remove:
                self._jobs.pop(j.job_id, None)
                self._stop_events.pop(j.job_id, None)
                self._threads.pop(j.job_id, None)

    def shutdown(self) -> None:
        """Gracefully signals all active jobs to terminate."""
        with self._lock:
            self._is_shutdown = True
            for ev in self._stop_events.values():
                ev.set()


# Module-level singleton
_default_manager: Optional[VideoJobManager] = None
_manager_lock = threading.Lock()


def get_video_job_manager() -> VideoJobManager:
    """Retrieve or initialize the global VideoJobManager singleton."""
    global _default_manager
    with _manager_lock:
        if _default_manager is None:
            _default_manager = VideoJobManager(max_concurrent=2)
        return _default_manager

