#!/usr/bin/env python3
"""Cross-platform local Mini-CI runner mirroring .github/workflows/ci.yml."""

import argparse
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WSL_DISTRO = os.environ.get("MINI_CI_WSL_DISTRO", "Ubuntu-24.04")
WSL_VENV_DIR = "$HOME/.venvs/intelligent_tracker"
RUFF_IGNORE = "E501,E722,E741,F401,F841"
DOCKER_BASE_IMAGE = "python:3.12-slim"
DOCKER_IMAGE_PREFIX = "intelligent-tracker-mini-ci"
SNAPSHOT_EXCLUDE_DIRS = {
    ".git", ".venv", ".mypy_cache", ".ruff_cache",
    "__pycache__", ".pytest_cache", "node_modules", ".diagnostics",
}


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for the local mini-CI runner."""
    parser = argparse.ArgumentParser(description="Local mini-CI runner mirroring GitHub Actions.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fast", action="store_true", help="Run in host .venv with clean env (default).")
    mode.add_argument("--linux", action="store_true", help="Run in Linux (WSL or Docker) for CI parity.")
    parser.add_argument("--backend", choices=("auto", "wsl", "docker"), default="auto", help="Linux backend.")
    parser.add_argument("--wsl-distro", default=DEFAULT_WSL_DISTRO, help="WSL distro name for --linux.")
    parser.add_argument("--tests", nargs="+", default=None, help="Specific test files instead of full suite.")
    parser.add_argument("--skip-lint", action="store_true", help="Skip ruff check step.")
    parser.add_argument("--skip-docs", action="store_true", help="Skip Sphinx documentation build.")
    parser.add_argument("--clean-snapshot", action="store_true", help="Exclude models/*.onnx and data/*.db.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands without executing.")
    args = parser.parse_args(argv)
    if not args.linux:
        args.fast = True
    return args


def requirements_hash(repo_root: Path = REPO_ROOT) -> str:
    """Return a stable 12-char SHA-256 digest of requirements.txt."""
    req_file = repo_root / "requirements.txt"
    return hashlib.sha256(req_file.read_bytes() if req_file.is_file() else b"").hexdigest()[:12]


def resolve_host_python(repo_root: Path = REPO_ROOT, platform: Optional[str] = None) -> Path:
    """Locate the repository .venv Python interpreter, falling back to sys.executable."""
    plat = platform or sys.platform
    win_py = repo_root / ".venv" / "Scripts" / "python.exe"
    posix_py = repo_root / ".venv" / "bin" / "python"
    for cand in ([win_py, posix_py] if plat.startswith("win") else [posix_py, win_py]):
        if cand.is_file():
            return cand
    return Path(sys.executable)


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


def create_clean_snapshot(repo_root: Path, dest_dir: Path) -> Path:
    """Copy repo_root into dest_dir while excluding local caches, DBs, and ONNX weights."""
    def _ignore(directory: str, names: list[str]) -> set[str]:
        rel = Path(directory).resolve().relative_to(repo_root.resolve())
        ignored = {n for n in names if n in SNAPSHOT_EXCLUDE_DIRS}
        if rel == Path("documentation") and "_build" in names:
            ignored.add("_build")
        if rel == Path("models"):
            ignored.update(n for n in names if n.endswith(".onnx"))
        if rel == Path("data"):
            ignored.update(n for n in names if n.endswith((".db", ".db-wal", ".db-shm")))
        return ignored

    shutil.copytree(repo_root, dest_dir, ignore=_ignore, dirs_exist_ok=True)
    return dest_dir


def build_fast_env(base_env: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Return a clean CI-parity environment without overriding USERPROFILE on Windows."""
    env = dict(os.environ if base_env is None else base_env)
    env["MPLBACKEND"] = "Agg"
    env["IT_DISABLE_EXTERNAL_SKILLS"] = "1"
    return env


def build_ci_step_commands(
    python_exe: str, *, tests: Optional[list[str]] = None, skip_lint: bool = False, skip_docs: bool = False
) -> list[tuple[str, list[str]]]:
    """Build ordered (label, argv) CI commands mirroring .github/workflows/ci.yml."""
    steps: list[tuple[str, list[str]]] = []
    if not skip_lint:
        steps.append(("Ruff Linter", [python_exe, "-m", "ruff", "check", ".", "--ignore", RUFF_IGNORE, "--statistics"]))
    if tests:
        steps.append(("Targeted Tests", [python_exe, "-m", "unittest", "-v", *tests]))
    else:
        steps.append(("Full Test Suite", [python_exe, "-m", "unittest", "discover", "tests"]))
    if not skip_docs:
        steps.append(("Sphinx Docs", [python_exe, "-m", "sphinx", "-b", "html", "documentation/", "documentation/_build/html"]))
    return steps


def _shell_ci_commands(
    python_expr: str, *, tests: Optional[list[str]] = None, skip_lint: bool = False, skip_docs: bool = False
) -> list[str]:
    """Build shell lines for Linux (WSL/Docker) CI steps."""
    cmds: list[str] = []
    if not skip_lint:
        cmds.append(f"{python_expr} -m ruff check . --ignore {RUFF_IGNORE} --statistics || true")
    if tests:
        cmds.append(f"{python_expr} -m unittest -v {' '.join(shlex.quote(t) for t in tests)}")
    else:
        cmds.append(f"{python_expr} -m unittest discover tests")
    if not skip_docs:
        cmds.append(f"{python_expr} -m sphinx -b html documentation/ documentation/_build/html")
    return cmds


def build_wsl_script(
    wsl_repo_path: str,
    req_hash: str,
    *,
    tests: Optional[list[str]] = None,
    skip_lint: bool = False,
    skip_docs: bool = False,
) -> str:
    """Build bash script that syncs a persistent ext4 WSL venv and runs CI in isolated HOME."""
    steps = "\n".join(_shell_ci_commands('"$VENV/bin/python"', tests=tests, skip_lint=skip_lint, skip_docs=skip_docs))
    return "\n".join([
        "set -euo pipefail",
        f'VENV="{WSL_VENV_DIR}"',
        'HASH_FILE="$VENV/.req_sha256"',
        f'REQ_HASH="{req_hash}"',
        f"cd {shlex.quote(wsl_repo_path)}",
        'if [ ! -x "$VENV/bin/python" ] || [ ! -f "$HASH_FILE" ] || [ "$(cat "$HASH_FILE")" != "$REQ_HASH" ]; then',
        '  mkdir -p "$(dirname "$VENV")"',
        '  python3 -m venv "$VENV"',
        '  "$VENV/bin/python" -m pip install --upgrade pip setuptools wheel',
        '  "$VENV/bin/pip" install -r requirements.txt ruff sphinx sphinx-rtd-theme',
        '  printf "%s" "$REQ_HASH" > "$HASH_FILE"',
        "fi",
        'CLEAN_HOME="$(mktemp -d /tmp/mini_ci_home.XXXXXX)"',
        'trap \'rm -rf "$CLEAN_HOME"\' EXIT',
        'export HOME="$CLEAN_HOME"',
        'export MPLBACKEND="Agg"',
        'export IT_DISABLE_EXTERNAL_SKILLS="1"',
        steps,
    ])


def build_wsl_command(distro: str, script: str) -> list[str]:
    """Build the wsl.exe invocation for executing a bash script."""
    return ["wsl", "-d", distro, "--", "bash", "-lc", script]


def docker_image_tag(req_hash: str) -> str:
    """Return deterministic Docker image tag keyed by requirements.txt hash."""
    return f"{DOCKER_IMAGE_PREFIX}:{req_hash}"


def build_dockerfile() -> str:
    """Return Dockerfile text mirroring .github/workflows/ci.yml on python:3.12-slim."""
    return "\n".join([
        f"FROM {DOCKER_BASE_IMAGE}",
        "RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 ffmpeg && rm -rf /var/lib/apt/lists/*",
        "COPY requirements.txt /tmp/requirements.txt",
        "RUN python -m pip install --upgrade pip setuptools wheel && "
        "pip install --no-cache-dir -r /tmp/requirements.txt ruff sphinx sphinx-rtd-theme",
        "WORKDIR /workspace",
    ])


def build_docker_run_command(
    work_dir: Path,
    image_tag: str,
    *,
    tests: Optional[list[str]] = None,
    skip_lint: bool = False,
    skip_docs: bool = False,
) -> list[str]:
    """Build the docker run command with isolated HOME and clean-env flags."""
    inner = " && ".join([
        "mkdir -p /tmp/mini_ci_home",
        *_shell_ci_commands("python", tests=tests, skip_lint=skip_lint, skip_docs=skip_docs),
    ])
    return [
        "docker", "run", "--rm", "-e", "MPLBACKEND=Agg",
        "-e", "IT_DISABLE_EXTERNAL_SKILLS=1", "-e", "HOME=/tmp/mini_ci_home",
        "-v", f"{work_dir.resolve()}:/workspace", "-w", "/workspace",
        image_tag, "bash", "-lc", inner,
    ]


def _run_fast(args: argparse.Namespace, work_dir: Path) -> int:
    env = build_fast_env()
    steps = build_ci_step_commands(
        str(resolve_host_python(REPO_ROOT)), tests=args.tests, skip_lint=args.skip_lint, skip_docs=args.skip_docs
    )
    for label, cmd in steps:
        print(f"[mini_ci --fast] {label}: {' '.join(cmd)}")
        if args.dry_run:
            continue
        res = subprocess.run(cmd, cwd=work_dir, env=env, check=False)
        if res.returncode != 0 and label == "Ruff Linter":
            print(f"[mini_ci --fast] WARN ({res.returncode}): {label} (non-blocking, mirrors ci.yml)", file=sys.stderr)
            continue
        if res.returncode != 0:
            print(f"[mini_ci --fast] FAILED ({res.returncode}): {label}", file=sys.stderr)
            return res.returncode
    return 0


def _ensure_docker_image(image_tag: str, repo_root: Path, dry_run: bool) -> int:
    if not dry_run:
        probe = subprocess.run(["docker", "image", "inspect", image_tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if probe.returncode == 0:
            return 0
    with tempfile.TemporaryDirectory(prefix="mini_ci_docker_") as tmp:
        ctx = Path(tmp)
        (ctx / "Dockerfile").write_text(build_dockerfile(), encoding="utf-8")
        shutil.copy2(repo_root / "requirements.txt", ctx / "requirements.txt")
        build_cmd = ["docker", "build", "-t", image_tag, str(ctx)]
        print(f"[mini_ci --linux/docker] Build image: {' '.join(build_cmd)}")
        return 0 if dry_run else subprocess.run(build_cmd, check=False).returncode


def _run_linux(args: argparse.Namespace, work_dir: Path) -> int:
    backend = select_linux_backend(args.backend)
    req_hash = requirements_hash(REPO_ROOT)
    if backend == "wsl":
        script = build_wsl_script(windows_to_wsl_path(work_dir), req_hash, tests=args.tests, skip_lint=args.skip_lint, skip_docs=args.skip_docs)
        print(f"[mini_ci --linux/wsl] distro={args.wsl_distro} req_hash={req_hash}")
        if args.dry_run:
            print(script)
            return 0
        return subprocess.run(build_wsl_command(args.wsl_distro, script), check=False).returncode

    tag = docker_image_tag(req_hash)
    rc = _ensure_docker_image(tag, REPO_ROOT, args.dry_run)
    if rc != 0:
        return rc
    cmd = build_docker_run_command(work_dir, tag, tests=args.tests, skip_lint=args.skip_lint, skip_docs=args.skip_docs)
    print(f"[mini_ci --linux/docker] Run: {' '.join(cmd)}")
    return 0 if args.dry_run else subprocess.run(cmd, check=False).returncode


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for scripts/mini_ci.py."""
    args = parse_args(argv)
    if args.clean_snapshot:
        with tempfile.TemporaryDirectory(prefix="mini_ci_snapshot_") as tmp:
            snap = create_clean_snapshot(REPO_ROOT, Path(tmp) / "repo")
            return _run_linux(args, snap) if args.linux else _run_fast(args, snap)
    return _run_linux(args, REPO_ROOT) if args.linux else _run_fast(args, REPO_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
