# Local Mini-CI Parity Plan (`scripts/mini_ci.py`)

> **Goal:** Eliminate push-time GitHub Actions surprises across Windows, macOS, and Linux by providing a single cross-platform local mini-CI runner (`scripts/mini_ci.py`) with `--fast` (host `.venv`, clean env) and `--linux` (true `ubuntu-latest` parity via WSL `Ubuntu-24.04` or Docker) without ever colliding with the host `.venv`.

## Architectural Pre-Flight

- **Invariants:**
  1. Never share a `.venv` directory between Windows and WSL Linux. Host `.venv` stays untouched; WSL keeps a persistent Linux venv in native ext4 (`~/.venvs/intelligent_tracker`), synced only when `requirements.txt` hash changes.
  2. Never override `USERPROFILE` on Windows (which stalls unrelated Windows tests); instead, support an explicit `IT_DISABLE_EXTERNAL_SKILLS=1` env gate in `dashboard/services/diagnostic_bridge.py` so `--fast` simulates a skill-free CI runner cleanly on Windows, macOS, and Linux.
  3. Mirror `.github/workflows/ci.yml` steps (`ruff check`, `MPLBACKEND=Agg python -m unittest discover tests`, `sphinx-build -b html documentation/ documentation/_build/html`) with `HOME` isolated in `--linux` mode and untracked local artifacts (`models/*.onnx`, `data/*.db`) excluded when `--clean-snapshot` is used.
  4. Stay strictly under modularity budgets (`<= 350` lines/file, `<= 40` lines/function, 0 ruff/mypy issues).

## Scenario Combinations Matrix

| Platform | Command | Venv Used | Skill Isolation | OS/Case Parity |
| :--- | :--- | :--- | :--- | :--- |
| Windows / macOS / Linux | `python scripts/mini_ci.py --fast` | Host `.venv` | `IT_DISABLE_EXTERNAL_SKILLS=1` | Host OS |
| Windows (with WSL) | `python scripts/mini_ci.py --linux` | WSL `~/.venvs/intelligent_tracker` | Clean `HOME=/tmp/...` + flag | Ubuntu 24.04 / Py 3.12 |
| macOS / Linux / Windows | `python scripts/mini_ci.py --linux --backend docker` | Cached `python:3.12-slim` image | Container `HOME=/tmp/...` + flag | Debian/Linux / Py 3.12 |
| Any (targeted PR check) | `python scripts/mini_ci.py --fast --tests tests/test_diagnostics_contract.py` | Host `.venv` | `IT_DISABLE_EXTERNAL_SKILLS=1` | Host OS (seconds) |

## Milestone 1: Clean-Env Gate & Cross-Platform `scripts/mini_ci.py`

- [x] **dashboard/services/diagnostic_bridge.py**: Return `[]` from `_engine_candidates()` when `IT_DISABLE_EXTERNAL_SKILLS=1` so clean-env runs on Windows, macOS, and Linux never leak `~/.gemini` or `~/.claude` skills.
- [x] **scripts/mini_ci.py**: Implement OS-agnostic mini-CI runner (`<= 280L`, stdlib only) supporting `--fast` (host `.venv`), `--linux` (`--backend auto|wsl|docker`), `--tests <paths...>`, `--skip-docs`, `--skip-lint`, and automatic `requirements.txt` hash-based venv/image reuse.
- [x] **tests/test_mini_ci.py**: Add isolated unit tests verifying `IT_DISABLE_EXTERNAL_SKILLS=1` disables external skill discovery, CLI flag parsing, venv hash caching, and command construction across `--fast`, `wsl`, and `docker` backends.
- [x] **AGENTS.md**: Add a concise 1-line note under Section 4 referencing `scripts/mini_ci.py --fast` (pre-handoff) and `--linux` (pre-PR push), keeping `AGENTS.md` strictly under 10 KB.

**Verifier:** `python -m unittest -v tests/test_mini_ci.py tests/test_diagnostics_contract.py tests/test_dashboard_debug_hud.py tests/test_trace_recording_id.py` and `python scripts/mini_ci.py --fast --tests tests/test_mini_ci.py tests/test_diagnostics_contract.py`

**Exit Criteria:** All unit tests pass, `scripts/mini_ci.py --fast` passes with `IT_DISABLE_EXTERNAL_SKILLS=1`, and `diagnose.py audit --max-lines 350` passes with 0 lint/type errors.

## Milestone 2 (Deferred to Next Turn): WSL / Docker `--linux` Live Verification

*Deferred to Next Turn / Milestone* — Verify `scripts/mini_ci.py --linux` end-to-end against `Ubuntu-24.04` (after confirming `python3-venv` + `ffmpeg` or Docker backend) and record any one-time setup notes in `documentation/dashboard.rst` or `SETUP_GUIDE.md`.
