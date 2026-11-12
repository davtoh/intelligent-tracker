"""Unit tests for scripts/run_dashboard.py CLI argument and configuration resolution."""

import unittest
from unittest.mock import patch

from scripts.run_dashboard import parse_args, resolve_config


class TestRunDashboardConfig(unittest.TestCase):
    """Verify configuration resolution for run_dashboard launcher."""

    def test_default_config(self) -> None:
        """Defaults should read from env or fallback to 0.0.0.0, 8000, reload=True."""
        with patch.dict("os.environ", {}, clear=True):
            args = parse_args([])
            host, port, reload_flag = resolve_config(args)
            self.assertEqual(host, "0.0.0.0")
            self.assertEqual(port, 8000)
            self.assertTrue(reload_flag)

    def test_local_flag_overrides_host(self) -> None:
        """The --local flag must strictly enforce 127.0.0.1 even if HOST env or --host is set."""
        with patch.dict("os.environ", {"HOST": "192.168.1.50"}, clear=True):
            args = parse_args(["--local"])
            host, port, reload_flag = resolve_config(args)
            self.assertEqual(host, "127.0.0.1")

    def test_local_flag_precedence_over_explicit_host(self) -> None:
        """The --local flag takes precedence when both --local and --host are supplied."""
        args = parse_args(["--host", "0.0.0.0", "--local"])
        host, port, reload_flag = resolve_config(args)
        self.assertEqual(host, "127.0.0.1")

    def test_explicit_host_and_port_args(self) -> None:
        """Explicit CLI args --host and --port should override defaults and env vars."""
        with patch.dict("os.environ", {"HOST": "0.0.0.0", "PORT": "9000"}, clear=True):
            args = parse_args(["--host", "10.0.0.5", "--port", "8080"])
            host, port, reload_flag = resolve_config(args)
            self.assertEqual(host, "10.0.0.5")
            self.assertEqual(port, 8080)

    def test_reload_flags(self) -> None:
        """--no-reload should disable reload, --reload should enable reload."""
        args_no_reload = parse_args(["--no-reload"])
        _, _, reload_no = resolve_config(args_no_reload)
        self.assertFalse(reload_no)

        args_reload = parse_args(["--reload"])
        _, _, reload_yes = resolve_config(args_reload)
        self.assertTrue(reload_yes)

    def test_env_var_fallback(self) -> None:
        """Environment variables HOST, PORT, and RELOAD must be respected when CLI args omitted."""
        env = {"HOST": "192.168.1.100", "PORT": "7000", "RELOAD": "false"}
        with patch.dict("os.environ", env, clear=True):
            args = parse_args([])
            host, port, reload_flag = resolve_config(args)
            self.assertEqual(host, "192.168.1.100")
            self.assertEqual(port, 7000)
            self.assertFalse(reload_flag)


if __name__ == "__main__":
    unittest.main()
