#!/usr/bin/env python3
"""Standalone cross-platform local Mini-CI runner mirroring .github/workflows/ci.yml.

Reads `.diagnostics/mini_ci.json` as shared config SSOT (zero external skill dependency).
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / ".diagnostics" / "mini_ci.json"
DEFAULT_WSL_DISTRO = os.environ.get("MINI_CI_WSL_DISTRO", "Ubuntu-24.04")
DOCKER_BASE_IMAGE = "python:3.12-slim"
DOCKER_IMAGE_PREFIX = "intelligent-tracker-mini-ci"
DEFAULT_EXCLUDES = {
    ".git", ".venv", ".mypy_cache", ".ruff_cache",
    "__pycache__", ".pytest_cache", "node_modules", ".diagnostics",
}


def load_config(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Load optional `.diagnostics/mini_ci.json` shared CI configuration."""
    cfg_file = repo_root / ".diagnostics" / "mini_ci.json"
    if not cfg_file.is_file():
        return {}
    raw = json.loads(cfg_file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{cfg_file} must contain a JSON object.")
    return raw


def parse_args(argv: Optional[list[str]] = None, config: Optional[dict[str, Any]] = None) -> argparse.Namespace:
    """Parse CLI arguments for the standalone local mini-CI runner."""
    cfg = config or {}
    parser = argparse.ArgumentParser(description="Standalone local mini-CI runner mirroring GitHub Actions.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fast", action="store_true", help="Run in host .venv with clean env (default).")
    mode.add_argument("--linux", action="store_true", help="Run in Linux (WSL or Docker) for CI parity.")
    parser.add_argument("--backend", choices=("auto", "wsl", "docker"), default="auto", help="Linux backend.")
    parser.add_argument("--wsl-distro", default=cfg.get("wsl_distro") or DEFAULT_WSL_DISTRO, help="WSL distro name.")
    parser.add_argument("--tests", nargs="+", default=None, help="Specific test files instead of full suite.")
    parser.add_argument("--skip-lint", action="store_true", help="Skip ruff check step.")
    parser.add_argument("--skip-docs", action="store_true", help="Skip Sphinx documentation build.")
    parser.add_argument("--clean-snapshot", action="store_true", help="Run in temp copy excluding local data/models.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands without executing.")
    args = parser.parse_args(argv)
    if not args.linux:
        args.fast = True
    return args


def resolve_host_python(repo_root: Path = REPO_ROOT, platform: Optional[str] = None) -> Path:
    """Locate the repository .venv Python interpreter, falling back to sys.executable."""
    plat = platform or sys.platform
    cand = (
        repo_root / ".venv" / "Scripts" / "python.exe"
        if plat.startswith("win")
        else repo_root / ".venv" / "bin" / "python"
    )
    return cand if cand.is_file() else Path(sys.executable)


def windows_to_wsl_path(path: Path) -> str:
    """Convert a Windows path (e.g. C:\\dev\\repo) to a WSL mount path (/mnt/c/dev/repo)."""
    raw = str(path)
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        rest = raw[2:].replace("\\", "/").lstrip("/")
        return f"/mnt/{raw[0].lower()}/{rest}" if rest else f"/mnt/{raw[0].lower()}"
    return raw.replace("\\", "/")


def select_linux_backend(requested: str, platform: Optional[str] = None) -> str:
    """Resolve 'auto' to 'wsl' (Windows with wsl.exe) or 'docker'."""
    if requested in ("wsl", "docker"):
        return requested
    plat = platform or sys.platform
    if plat.startswith("win") and shutil.which("wsl"):
        return "wsl"
    if shutil.which("docker"):
        return "docker"
    return "wsl" if plat.startswith("win") else "docker"


def create_clean_snapshot(
    repo_root: Path, dest_dir: Path, exclude_dirs: Optional[list[str]] = None
) -> Path:
    """Copy repo_root into dest_dir while excluding caches and configured exclude_dirs."""
    excludes = DEFAULT_EXCLUDES | set(exclude_dirs or ())
    shutil.copytree(
        repo_root,
        dest_dir,
        ignore=lambda _d, names: {n for n in names if n in excludes},
        dirs_exist_ok=True,
    )
    return dest_dir


def build_fast_env(
    base_env: Optional[dict[str, str]] = None, config: Optional[dict[str, Any]] = None
) -> dict[str, str]:
    """Return a clean CI-parity environment without overriding USERPROFILE on Windows."""
    env = dict(os.environ if base_env is None else base_env)
    env.update({"CI": "true", "MPLBACKEND": "Agg", "PYTHONUTF8": "1"})
    for key, val in (config or {}).get("env", {}).items():
        env[str(key)] = str(val)
    env.setdefault("IT_DISABLE_EXTERNAL_SKILLS", "1")
    return env


def _step_kind(tokens: list[str]) -> str:
    joined = " ".join(tokens).lower()
    if "ruff" in joined or "flake8" in joined:
        return "lint"
    if "sphinx" in joined:
        return "docs"
    return "test"


def build_ci_step_commands(
    python_exe: str,
    *,
    config: Optional[dict[str, Any]] = None,
    tests: Optional[list[str]] = None,
    skip_lint: bool = False,
    skip_docs: bool = False,
) -> list[list[str]]:
    """Build ordered argv CI commands from `.diagnostics/mini_ci.json` (or defaults)."""
    if tests:
        return [[python_exe, "-m", "unittest", "-v", *tests]]
    raw_steps = (config or {}).get("steps") or [
        ["{python}", "-m", "ruff", "check", ".", "--ignore", "E501,E722,E741,F401,F841", "--statistics", "--exit-zero"],
        ["{python}", "-m", "unittest", "discover", "tests"],
        ["{python}", "-m", "sphinx", "-b", "html", "documentation/", "documentation/_build/html"],
    ]
    steps: list[list[str]] = []
    for item in raw_steps:
        tokens = [str(t) for t in item] if isinstance(item, list) else shlex.split(str(item))
        resolved = [python_exe if t == "{python}" else t for t in tokens]
        kind = _step_kind(resolved)
        if (skip_lint and kind == "lint") or (skip_docs and kind == "docs"):
            continue
        steps.append(resolved)
    return steps


def _render_shell_cmd(tokens: list[str], py_placeholder: str, py_expr: str) -> str:
    return " ".join(py_expr if t == py_placeholder else shlex.quote(t) for t in tokens)


def build_wsl_script(
    wsl_repo_path: str, config: dict[str, Any], *,
    tests: Optional[list[str]] = None, skip_lint: bool = False, skip_docs: bool = False,
) -> str:
    """Build bash script that caches an ext4 WSL venv and runs CI in isolated HOME."""
    py_tok = "__PY__"
    steps = build_ci_step_commands(py_tok, config=config, tests=tests, skip_lint=skip_lint, skip_docs=skip_docs)
    apt_pkgs = [str(p) for p in config.get("apt_packages", ["libgl1", "libglib2.0-0", "ffmpeg", "nodejs"])]
    pip_pkgs = [str(p) for p in config.get("pip_packages", ["ruff", "sphinx", "sphinx-rtd-theme"])]
    extra_pip = " ".join(shlex.quote(p) for p in pip_pkgs)
    apt_hint = " ".join(["python3-venv", *apt_pkgs])
    env_exports = [f"export {k}={shlex.quote(str(v))}" for k, v in config.get("env", {"IT_DISABLE_EXTERNAL_SKILLS": "1"}).items()]
    lines = [
        "set -euo pipefail",
        'CLEAN_HOME="$(mktemp -d /tmp/mini_ci_home.XXXXXX)"',
        'trap \'rm -rf "$CLEAN_HOME"\' EXIT',
        'export HOME="$CLEAN_HOME" CI=true MPLBACKEND=Agg PYTHONUTF8=1',
        *env_exports,
        f"cd {shlex.quote(wsl_repo_path)}",
        'REQ_HASH="$({ [ -f requirements.txt ] && cat requirements.txt; printf "%s" ' + shlex.quote(extra_pip) + '; } | sha256sum | cut -c1-12)"',
        'VENV="/tmp/mini_ci_venvs/$REQ_HASH"',
        'if [ ! -f "$VENV/.ready" ]; then',
        '  if ! python3 -c "import ensurepip" >/dev/null 2>&1; then',
        '    echo "[mini_ci --linux/wsl] Missing python3-venv in WSL. Install with:" >&2',
        f'    echo "  sudo apt-get update && sudo apt-get install -y {apt_hint}" >&2',
        '    echo "Or run with Docker instead: python scripts/mini_ci.py --linux --backend docker" >&2',
        "    exit 2",
        "  fi",
        '  rm -rf "$VENV" && python3 -m venv "$VENV"',
        '  "$VENV/bin/python" -m pip install -q --upgrade pip setuptools wheel',
        '  [ -f requirements.txt ] && "$VENV/bin/python" -m pip install -q -r requirements.txt',
        *([f'  "$VENV/bin/python" -m pip install -q {extra_pip}'] if pip_pkgs else []),
        '  touch "$VENV/.ready"',
        "fi",
        *(_render_shell_cmd(s, py_tok, '"$VENV/bin/python"') for s in steps),
    ]
    return "\n".join(lines) + "\n"


def build_dockerfile(config: dict[str, Any]) -> str:
    """Return Dockerfile text built from `.diagnostics/mini_ci.json`."""
    base = str(config.get("docker_image") or DOCKER_BASE_IMAGE)
    apt_pkgs = [str(p) for p in config.get("apt_packages", ["libgl1", "libglib2.0-0", "ffmpeg", "nodejs"])]
    pip_pkgs = [str(p) for p in config.get("pip_packages", ["ruff", "sphinx", "sphinx-rtd-theme"])]
    lines = [f"FROM {base}"]
    if apt_pkgs:
        lines.append(f"RUN apt-get update && apt-get install -y --no-install-recommends {' '.join(apt_pkgs)} && rm -rf /var/lib/apt/lists/*")
    lines.extend([
        "WORKDIR /workspace",
        "COPY requirements.txt /tmp/requirements.txt",
        "RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && "
        f"pip install --no-cache-dir -r /tmp/requirements.txt {' '.join(pip_pkgs)}".rstrip(),
    ])
    return "\n".join(lines) + "\n"


def docker_image_tag(dockerfile: str, req_file: Optional[Path] = None) -> str:
    """Return content-addressed Docker image tag from Dockerfile + requirements.txt."""
    digest = hashlib.sha256(dockerfile.encode("utf-8"))
    if req_file and req_file.is_file():
        digest.update(b"\0")
        digest.update(req_file.read_bytes())
    return f"{DOCKER_IMAGE_PREFIX}:{digest.hexdigest()[:12]}"


def build_docker_run_command(
    work_dir: Path,
    image_tag: str,
    config: dict[str, Any],
    *,
    tests: Optional[list[str]] = None,
    skip_lint: bool = False,
    skip_docs: bool = False,
) -> list[str]:
    """Build `docker run --rm` argv with isolated HOME and configured env vars."""
    py_tok = "__PY__"
    steps = build_ci_step_commands(py_tok, config=config, tests=tests, skip_lint=skip_lint, skip_docs=skip_docs)
    inner = " && ".join(["mkdir -p /tmp/mini_ci_home", *(_render_shell_cmd(s, py_tok, "python3") for s in steps)])
    cmd = [
        "docker", "run", "--rm", "-e", "CI=true", "-e", "MPLBACKEND=Agg", "-e", "HOME=/tmp/mini_ci_home",
    ]
    for key, val in config.get("env", {"IT_DISABLE_EXTERNAL_SKILLS": "1"}).items():
        cmd.extend(["-e", f"{key}={val}"])
    return cmd + ["-v", f"{work_dir.resolve()}:/workspace", "-w", "/workspace", image_tag, "bash", "-lc", inner]


def _ensure_docker_image(tag: str, dockerfile: str, req_file: Path, dry_run: bool) -> int:
    if not dry_run:
        probe = subprocess.run(["docker", "image", "inspect", tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if probe.returncode == 0:
            return 0
    with tempfile.TemporaryDirectory(prefix="mini_ci_docker_") as tmp:
        ctx = Path(tmp)
        (ctx / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        if req_file.is_file():
            shutil.copy2(req_file, ctx / "requirements.txt")
        build_cmd = ["docker", "build", "-t", tag, str(ctx)]
        print(f"[mini_ci --linux/docker] Build image: {' '.join(build_cmd)}")
        return 0 if dry_run else subprocess.run(build_cmd, check=False).returncode


def _run_fast(args: argparse.Namespace, work_dir: Path, config: dict[str, Any]) -> int:
    env = build_fast_env(config=config)
    steps = build_ci_step_commands(
        str(resolve_host_python(REPO_ROOT)), config=config, tests=args.tests, skip_lint=args.skip_lint, skip_docs=args.skip_docs
    )
    for idx, cmd in enumerate(steps, 1):
        print(f"[mini_ci --fast] [{idx}/{len(steps)}] {' '.join(cmd)}")
        if not args.dry_run:
            res = subprocess.run(cmd, cwd=work_dir, env=env, check=False)
            if res.returncode != 0:
                return res.returncode
    return 0


def _run_linux(args: argparse.Namespace, work_dir: Path, config: dict[str, Any]) -> int:
    backend = select_linux_backend(args.backend)
    if backend == "wsl":
        script = build_wsl_script(windows_to_wsl_path(work_dir), config, tests=args.tests, skip_lint=args.skip_lint, skip_docs=args.skip_docs)
        print(f"[mini_ci --linux/wsl] distro={args.wsl_distro}")
        if args.dry_run:
            print(script, end="")
            return 0
        return subprocess.run(["wsl", "-d", args.wsl_distro, "--", "bash", "-s"], input=script.encode("utf-8"), check=False).returncode
    dockerfile = build_dockerfile(config)
    req_file = REPO_ROOT / "requirements.txt"
    tag = docker_image_tag(dockerfile, req_file)
    rc = _ensure_docker_image(tag, dockerfile, req_file, args.dry_run)
    if rc != 0:
        return rc
    cmd = build_docker_run_command(work_dir, tag, config, tests=args.tests, skip_lint=args.skip_lint, skip_docs=args.skip_docs)
    print(f"[mini_ci --linux/docker] Run: {' '.join(cmd)}")
    return 0 if args.dry_run else subprocess.run(cmd, check=False).returncode


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for scripts/mini_ci.py."""
    config = load_config(REPO_ROOT)
    args = parse_args(argv, config=config)
    if args.clean_snapshot:
        with tempfile.TemporaryDirectory(prefix="mini_ci_snapshot_") as tmp:
            snap = create_clean_snapshot(REPO_ROOT, Path(tmp) / "repo", exclude_dirs=config.get("exclude_dirs"))
            return _run_linux(args, snap, config) if args.linux else _run_fast(args, snap, config)
    return _run_linux(args, REPO_ROOT, config) if args.linux else _run_fast(args, REPO_ROOT, config)


if __name__ == "__main__":
    raise SystemExit(main())
