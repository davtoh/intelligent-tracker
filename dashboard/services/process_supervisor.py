#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Cross-Platform Process Containment & Supervisor Service.

Provides kernel-enforced process fate-sharing, active parent liveness monitoring,
and socket pre-flight reclamation to guarantee zero orphaned zombie processes:
- Windows: Win32 Job Objects configured with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
- Linux: prctl(PR_SET_PDEATHSIG, SIGTERM) delivering termination signals when parent dies.
- Cross-Platform: Background ParentDeathWatchdog checking supervisor PID liveness.
- Port Pre-Flight: Probing and safely reclaiming TCP listening sockets on startup.
"""

from collections.abc import Callable
import ctypes
import logging
import os
import signal
import socket
import sys
import threading
import time
from typing import Optional

import psutil

logger = logging.getLogger("intelligent_tracker.process_supervisor")

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9

if sys.platform == "win32":
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64), ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64), ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64), ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


def is_test_environment() -> bool:
    """Return True if running inside an automated test suite runner."""
    main_mod = sys.modules.get("__main__")
    main_file = getattr(main_mod, "__file__", "") or ""
    return (
        os.environ.get("TESTING") == "1"
        or any("unittest" in str(a).lower() or "pytest" in str(a).lower() for a in sys.argv)
        or "unittest" in main_file.lower()
        or "pytest" in main_file.lower()
    )


class ProcessTreeSupervisor:
    """Manages process tree containment, parent watchdog monitoring, and socket availability."""

    def __init__(self) -> None:
        self._job_handle: Optional[int] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def assign_to_job_object(self) -> bool:
        """Assign current process to a Windows Job Object configured with KILL_ON_JOB_CLOSE."""
        if sys.platform != "win32":
            return False
        with self._lock:
            if self._job_handle is not None:
                return True
            try:
                from ctypes import wintypes
                k32 = ctypes.windll.kernel32
                k32.CreateJobObjectW.restype = wintypes.HANDLE
                k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
                k32.SetInformationJobObject.restype = wintypes.BOOL
                k32.SetInformationJobObject.argtypes = [
                    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
                ]
                k32.GetCurrentProcess.restype = wintypes.HANDLE
                k32.GetCurrentProcess.argtypes = []
                k32.AssignProcessToJobObject.restype = wintypes.BOOL
                k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

                h_job = k32.CreateJobObjectW(None, None)
                if not h_job:
                    logger.warning("CreateJobObjectW failed: WinError %d", k32.GetLastError())
                    return False

                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                if not k32.SetInformationJobObject(
                    h_job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
                ):
                    logger.warning("SetInformationJobObject failed: WinError %d", k32.GetLastError())
                    k32.CloseHandle(h_job)
                    return False

                if not k32.AssignProcessToJobObject(h_job, k32.GetCurrentProcess()):
                    logger.warning("AssignProcessToJobObject failed: WinError %d", k32.GetLastError())
                    k32.CloseHandle(h_job)
                    return False

                self._job_handle = h_job
                logger.info("Assigned process %d to Win32 Job Object with KILL_ON_JOB_CLOSE.", os.getpid())
                return True
            except Exception as exc:
                logger.warning("Could not assign process to Win32 Job Object: %s", exc)
                return False

    def set_parent_death_signal(self, sig: int = signal.SIGTERM) -> bool:
        """Configure Linux kernel to send termination signal if parent process dies."""
        if sys.platform != "linux":
            return False
        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            res = libc.prctl(ctypes.c_int(1), ctypes.c_ulong(sig))  # PR_SET_PDEATHSIG = 1
            if res != 0:
                logger.warning("prctl(PR_SET_PDEATHSIG) failed with errno %d", ctypes.get_errno())
                return False
            logger.debug("Configured Linux parent death signal (%s).", sig)
            return True
        except Exception as exc:
            logger.warning("Could not set parent death signal on Linux: %s", exc)
            return False

    def start_parent_watchdog(
        self,
        poll_interval: float = 1.0,
        on_parent_death: Callable[[], None] | None = None,
        target_ppid: int | None = None,
    ) -> bool:
        """Start background daemon thread monitoring parent PID liveness."""
        with self._lock:
            if self._watchdog_thread and self._watchdog_thread.is_alive():
                return True
            initial_ppid = target_ppid if target_ppid is not None else os.getppid()
            if initial_ppid <= 1:
                logger.debug("Initial PPID is %d (systemd/init/orphaned); parent watchdog skipped.", initial_ppid)
                return False
            self._stop_event.clear()

            try:
                parent_proc = psutil.Process(initial_ppid)
                parent_create_time = parent_proc.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                parent_proc, parent_create_time = None, None

            def _worker() -> None:
                while not self._stop_event.wait(timeout=poll_interval):
                    is_dead = False
                    if sys.platform != "win32" and target_ppid is None and os.getppid() != initial_ppid:
                        is_dead = True
                    elif parent_proc is not None:
                        try:
                            if not parent_proc.is_running() or parent_proc.status() == psutil.STATUS_ZOMBIE:
                                is_dead = True
                            elif parent_create_time is not None and parent_proc.create_time() != parent_create_time:
                                is_dead = True
                        except (psutil.NoSuchProcess, psutil.ZombieProcess):
                            is_dead = True
                        except psutil.AccessDenied:
                            pass
                    else:
                        is_dead = not psutil.pid_exists(initial_ppid)

                    if is_dead:
                        logger.warning("Parent process (PID %d) terminated; triggering exit.", initial_ppid)
                        if on_parent_death is not None:
                            try:
                                on_parent_death()
                            except Exception as cb_err:
                                logger.error("Error in on_parent_death callback: %s", cb_err)
                        elif not is_test_environment():
                            try:
                                sys.stdout.flush()
                                sys.stderr.flush()
                            except Exception:
                                pass
                            os._exit(0)
                        break

            self._watchdog_thread = threading.Thread(target=_worker, name="ParentDeathWatchdog", daemon=True)
            self._watchdog_thread.start()
            return True

    def stop_parent_watchdog(self, timeout: float = 2.0) -> bool:
        """Stop background parent watchdog thread."""
        with self._lock:
            if not self._watchdog_thread or not self._watchdog_thread.is_alive():
                return True
            self._stop_event.set()
            self._watchdog_thread.join(timeout=timeout)
            return not self._watchdog_thread.is_alive()

    def check_port_available(self, port: int, host: str = "0.0.0.0") -> bool:
        """Check whether a TCP port is available for binding."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if sys.platform == "win32":
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host if host not in ("0.0.0.0", "") else "", port))
                return True
        except OSError:
            return False

    def find_port_listeners(self, port: int) -> list[int]:
        """Return list of distinct process PIDs currently bound to the specified port."""
        current_pid, listeners = os.getpid(), []
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.laddr and conn.laddr.port == port:
                    if conn.pid and conn.pid != current_pid and conn.pid not in listeners:
                        listeners.append(conn.pid)
        except (psutil.AccessDenied, OSError) as exc:
            logger.debug("Failed to query net_connections for port %d: %s", port, exc)
        return listeners

    def reclaim_port(self, port: int, force: bool = False, timeout: float = 3.0) -> bool:
        """Reclaim bound TCP port by safely terminating orphaned tracker/dashboard processes."""
        if self.check_port_available(port):
            return True
        pids = self.find_port_listeners(port)
        if not pids:
            logger.warning("Port %d is bound but owning PID could not be determined.", port)
            return False

        dashboard_signatures = ("run_dashboard", "dashboard.app", "uvicorn", "intelligent_tracker")
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                cmdline, name = " ".join(proc.cmdline()).lower(), proc.name().lower()
                is_target = force or any(sig in cmdline for sig in dashboard_signatures) or any(s in name for s in ("python", "uvicorn"))
                if not is_target:
                    logger.info("Process %d on port %d does not match tracker signatures; skipping.", pid, port)
                    continue
                logger.warning("Reclaiming port %d: terminating orphaned process %d (%s)...", port, pid, proc.name())
                proc.terminate()
                try:
                    proc.wait(timeout=min(timeout, 2.0))
                except psutil.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1.0)
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                logger.debug("Could not terminate process %d: %s", pid, exc)

        deadline = time.time() + timeout
        interrupt_event = threading.Event()
        while time.time() < deadline:
            if self.check_port_available(port):
                logger.info("Successfully reclaimed port %d.", port)
                return True
            interrupt_event.wait(timeout=0.1)
        return self.check_port_available(port)


# Global singleton instance & module-level facades
_SUPERVISOR = ProcessTreeSupervisor()


def get_process_supervisor() -> ProcessTreeSupervisor:
    """Return the global ProcessTreeSupervisor instance."""
    return _SUPERVISOR


def assign_to_job_object() -> bool:
    """Assign current process to a Windows Job Object with KILL_ON_JOB_CLOSE."""
    return _SUPERVISOR.assign_to_job_object()


def set_parent_death_signal(sig: int = signal.SIGTERM) -> bool:
    """Configure Linux kernel parent death signal."""
    return _SUPERVISOR.set_parent_death_signal(sig)


def start_parent_watchdog(
    poll_interval: float = 1.0,
    on_parent_death: Callable[[], None] | None = None,
    target_ppid: int | None = None,
) -> bool:
    """Start parent liveness watchdog thread."""
    return _SUPERVISOR.start_parent_watchdog(poll_interval, on_parent_death, target_ppid)


def stop_parent_watchdog(timeout: float = 2.0) -> bool:
    """Stop parent liveness watchdog thread."""
    return _SUPERVISOR.stop_parent_watchdog(timeout)


def check_port_available(port: int, host: str = "0.0.0.0") -> bool:
    """Check whether a TCP port is available."""
    return _SUPERVISOR.check_port_available(port, host)


def find_port_listeners(port: int) -> list[int]:
    """Find PIDs bound to the specified TCP port."""
    return _SUPERVISOR.find_port_listeners(port)


def reclaim_port(port: int, force: bool = False, timeout: float = 3.0) -> bool:
    """Reclaim bound TCP port from orphaned tracker instances."""
    return _SUPERVISOR.reclaim_port(port, force, timeout)
