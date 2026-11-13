"""
Unit tests for ProcessTreeSupervisor, Win32 Job Objects, and Port Pre-Flight.
"""

from collections.abc import Callable
import os
import signal
import socket
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from dashboard.services.process_supervisor import (
    ProcessTreeSupervisor,
    assign_to_job_object,
    check_port_available,
    find_port_listeners,
    get_process_supervisor,
    is_test_environment,
    reclaim_port,
    set_parent_death_signal,
    start_parent_watchdog,
    stop_parent_watchdog,
)
from dashboard.services.windows_resilience import apply_windows_process_containment
from scripts.run_dashboard import preflight_port_check


class TestProcessSupervisor(unittest.TestCase):
    """Test suite for process tree containment, parent watchdog, and port reclamation."""

    def setUp(self) -> None:
        self.supervisor = ProcessTreeSupervisor()

    def tearDown(self) -> None:
        self.supervisor.stop_parent_watchdog(timeout=1.0)
        stop_parent_watchdog(timeout=1.0)

    def test_is_test_environment_true(self) -> None:
        """Verify is_test_environment accurately detects running under test runner."""
        self.assertTrue(is_test_environment())

    def test_assign_to_job_object_non_windows(self) -> None:
        """On non-Windows platforms, assign_to_job_object should safely return False."""
        with patch("sys.platform", "linux"):
            sup = ProcessTreeSupervisor()
            self.assertFalse(sup.assign_to_job_object())

    @unittest.skipUnless(sys.platform == "win32", "Win32 Job Object test requires Windows")
    def test_assign_to_job_object_real_windows(self) -> None:
        """On Windows, assign_to_job_object should successfully create and assign job."""
        sup = ProcessTreeSupervisor()
        result = sup.assign_to_job_object()
        self.assertTrue(result)
        # Calling again should return True idempotently
        self.assertTrue(sup.assign_to_job_object())

    def test_set_parent_death_signal_non_linux(self) -> None:
        """On non-Linux platforms, set_parent_death_signal safely returns False."""
        with patch("sys.platform", "win32"):
            sup = ProcessTreeSupervisor()
            self.assertFalse(sup.set_parent_death_signal())

    def test_set_parent_death_signal_linux_mock(self) -> None:
        """On Linux, prctl(PR_SET_PDEATHSIG) should be invoked via ctypes."""
        mock_libc = MagicMock()
        mock_libc.prctl.return_value = 0
        with patch("sys.platform", "linux"), patch("ctypes.CDLL", return_value=mock_libc):
            sup = ProcessTreeSupervisor()
            self.assertTrue(sup.set_parent_death_signal(signal.SIGTERM))
            mock_libc.prctl.assert_called_once()

    def test_start_parent_watchdog_init_or_orphaned_skipped(self) -> None:
        """If target parent PID is <= 1 (systemd/init), watchdog skips monitoring."""
        sup = ProcessTreeSupervisor()
        self.assertFalse(sup.start_parent_watchdog(target_ppid=1))
        self.assertFalse(sup.start_parent_watchdog(target_ppid=0))

    def test_start_parent_watchdog_detects_termination(self) -> None:
        """Watchdog detects simulated parent process death and triggers callback."""
        callback_called = threading.Event()

        def on_death() -> None:
            callback_called.set()

        fake_pid = 99999999
        sup = ProcessTreeSupervisor()
        started = sup.start_parent_watchdog(
            poll_interval=0.05,
            on_parent_death=on_death,
            target_ppid=fake_pid,
        )
        self.assertTrue(started)
        # Should trigger on_death callback since PID 99999999 does not exist
        triggered = callback_called.wait(timeout=2.0)
        self.assertTrue(triggered, "Expected parent death callback was not invoked")
        sup.stop_parent_watchdog()

    def test_parent_watchdog_clean_stop(self) -> None:
        """Watchdog should shut down cleanly within bounded timeout."""
        sup = ProcessTreeSupervisor()
        sup.start_parent_watchdog(poll_interval=1.0, target_ppid=os.getpid())
        self.assertTrue(sup.stop_parent_watchdog(timeout=1.0))

    def test_check_port_available_free_port(self) -> None:
        """An unbound ephemeral port should be detected as available."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            free_port = s.getsockname()[1]
        # Once socket closed, port is available
        self.assertTrue(self.supervisor.check_port_available(free_port))

    def test_check_port_available_bound_port(self) -> None:
        """A currently bound and listening socket should be detected as unavailable."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            bound_port = s.getsockname()[1]
            s.listen(1)
            self.assertFalse(self.supervisor.check_port_available(bound_port))

    def test_find_port_listeners_finds_current_process(self) -> None:
        """find_port_listeners should exclude current PID by default."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]
            s.listen(1)
            listeners = self.supervisor.find_port_listeners(port)
            self.assertNotIn(os.getpid(), listeners)

    def test_reclaim_port_already_free(self) -> None:
        """reclaim_port returns True immediately if port is already available."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]
        self.assertTrue(self.supervisor.reclaim_port(port))

    def test_reclaim_port_terminates_orphaned_process(self) -> None:
        """reclaim_port identifies matching dashboard processes and terminates them."""
        mock_proc = MagicMock()
        mock_proc.cmdline.return_value = ["python", "scripts/run_dashboard.py"]
        mock_proc.name.return_value = "python.exe"
        mock_proc.terminate.return_value = None
        mock_proc.wait.return_value = None

        with patch.object(self.supervisor, "check_port_available", side_effect=[False, True]), \
             patch.object(self.supervisor, "find_port_listeners", return_value=[4321]), \
             patch("psutil.Process", return_value=mock_proc):
            reclaimed = self.supervisor.reclaim_port(8000, force=False, timeout=1.0)
            self.assertTrue(reclaimed)
            mock_proc.terminate.assert_called_once()

    def test_reclaim_port_skips_unrelated_process_without_force(self) -> None:
        """reclaim_port ignores non-tracker processes when force=False."""
        mock_proc = MagicMock()
        mock_proc.cmdline.return_value = ["C:\\Windows\\System32\\svchost.exe", "-k", "netsvcs"]
        mock_proc.name.return_value = "svchost.exe"

        with patch.object(self.supervisor, "check_port_available", return_value=False), \
             patch.object(self.supervisor, "find_port_listeners", return_value=[9999]), \
             patch("psutil.Process", return_value=mock_proc):
            reclaimed = self.supervisor.reclaim_port(8000, force=False, timeout=0.2)
            self.assertFalse(reclaimed)
            mock_proc.terminate.assert_not_called()

    def test_preflight_port_check_reclaims_and_reports(self) -> None:
        """preflight_port_check in run_dashboard cleanly invokes reclaim_port."""
        with patch("dashboard.services.process_supervisor.check_port_available", side_effect=[False, True]), \
             patch("dashboard.services.process_supervisor.find_port_listeners", return_value=[1234]), \
             patch("dashboard.services.process_supervisor.reclaim_port", return_value=True):
            self.assertTrue(preflight_port_check(8000))

    def test_resilience_module_containment_hook(self) -> None:
        """apply_windows_process_containment should invoke assign_to_job_object."""
        with patch("dashboard.services.process_supervisor.assign_to_job_object", return_value=True):
            self.assertTrue(apply_windows_process_containment())


if __name__ == "__main__":
    unittest.main()

