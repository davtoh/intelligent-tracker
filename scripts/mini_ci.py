#!/usr/bin/env python3
"""Thin wrapper delegating local Mini-CI to `system-diagnostics` (`diagnose.py ci`).

Project configuration lives in `.diagnostics/mini_ci.json` (SSOT).
"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / ".diagnostics" / "mini_ci.json"


def resolve_host_python(repo_root: Path = REPO_ROOT, platform: Optional[str] = None) -> Path:
    """Locate the repository .venv Python interpreter, falling back to sys.executable."""
    plat = platform or sys.platform
    cand = (
        repo_root / ".venv" / "Scripts" / "python.exe"
        if plat.startswith("win")
        else repo_root / ".venv" / "bin" / "python"
    )
    return cand if cand.is_file() else Path(sys.executable)


def find_diagnose_script(env: Optional[dict[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
    """Locate `system-diagnostics/scripts/diagnose.py` via env var or standard skill roots."""
    environ = os.environ if env is None else env
    candidates: list[Path] = []
    if environ.get("SYSTEM_DIAGNOSTICS_DIR"):
        base = Path(environ["SYSTEM_DIAGNOSTICS_DIR"])
        candidates.extend([base / "scripts" / "diagnose.py", base / "diagnose.py"])
    user_home = home or Path.home()
    for rel in (
        ".gemini/config/skills/system-diagnostics/scripts/diagnose.py",
        ".agents/skills/system-diagnostics/scripts/diagnose.py",
        ".claude/skills/system-diagnostics/scripts/diagnose.py",
    ):
        candidates.append(user_home / rel)
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def build_diagnose_argv(
    diagnose_script: Path,
    argv: list[str],
    *,
    python_exe: Optional[Path] = None,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    """Build `diagnose.py ci --path <repo_root> ...` invocation."""
    py = str(python_exe or resolve_host_python(repo_root))
    forwarded = list(argv)
    if "--path" not in forwarded:
        forwarded = ["--path", str(repo_root), *forwarded]
    return [py, str(diagnose_script), "ci", *forwarded]


def _run_standalone_fast(argv: list[str], repo_root: Path = REPO_ROOT) -> int:
    """Fallback host runner using `.diagnostics/mini_ci.json` when `diagnose.py` is absent."""
    if "--linux" in argv:
        print(
            "[mini_ci] `system-diagnostics` not found; set SYSTEM_DIAGNOSTICS_DIR or install "
            "the skill to use `--linux`.",
            file=sys.stderr,
        )
        return 2
    cfg_file = repo_root / ".diagnostics" / "mini_ci.json"
    cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.is_file() else {}
    py = str(resolve_host_python(repo_root))
    env = dict(os.environ)
    env.update({"CI": "true", "MPLBACKEND": "Agg", "PYTHONUTF8": "1"})
    for key, val in cfg.get("env", {}).items():
        env[str(key)] = str(val)
    dry_run = "--dry-run" in argv
    raw_steps = cfg.get("steps") or [["{python}", "-m", "unittest", "discover", "tests"]]
    for item in raw_steps:
        tokens = [str(t) for t in item] if isinstance(item, list) else shlex.split(str(item))
        cmd = [py if t == "{python}" else t for t in tokens]
        print(f"[mini_ci standalone] {' '.join(cmd)}")
        if not dry_run:
            res = subprocess.run(cmd, cwd=str(repo_root), env=env, check=False)
            if res.returncode != 0:
                return res.returncode
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for scripts/mini_ci.py."""
    cli_args = list(sys.argv[1:] if argv is None else argv)
    diagnose_script = find_diagnose_script()
    if diagnose_script is None:
        return _run_standalone_fast(cli_args)
    cmd = build_diagnose_argv(diagnose_script, cli_args)
    return subprocess.run(cmd, cwd=str(REPO_ROOT), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
