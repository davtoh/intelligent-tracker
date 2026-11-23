# Implementation Plan: Cross-Platform Process Containment, Parent Liveness Watchdog & Camera Hardware Resilience (Tier 2)

## Executive Summary
This plan addresses recurring server process freezes, orphaned listening sockets on port `8000`, and kernel-driver stalls after OS sleep/hibernation.

When a terminal is closed or `CTRL+C` is pressed, standard Python reloaders (`uvicorn.supervisors.basereload.BaseReload`) can leave orphaned child or supervisor processes holding the TCP port. Concurrently, if physical webcams or virtual drivers (DirectShow/MSMF on Windows, V4L2 on Linux, AVFoundation on macOS) stall in native C++ calls during system sleep/wake cycles, acquisition threads cannot exit, causing graceful shutdown to hang indefinitely.

By implementing **Tier 2 (Frontier SOTA)**, the platform gains:
1. **Kernel-Enforced Process Tree Fate-Sharing**:
   - **Windows**: Win32 Job Objects configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` ensure child worker processes are atomically terminated by the OS kernel the instant the parent terminal or launcher dies.
   - **Linux**: `prctl(PR_SET_PDEATHSIG, SIGTERM)` delivers an immediate termination signal to child processes if their parent terminates.
   - **macOS / Unix Fallback**: Process group termination (`os.killpg`) backed by an active parent liveness monitor.
2. **Active Parent Liveness Watchdog (`ParentDeathWatchdog`)**:
   - A lightweight background daemon in child worker processes continuously monitors the health of the supervisor parent. If the parent vanishes (e.g. abrupt shell termination, force-close), the child unbinds hardware handles and triggers immediate clean process exit (`os._exit(0)`).
3. **Resilient Reloader & Startup Port Pre-Flight (`scripts/run_dashboard.py`)**:
   - Before binding to port `8000`, a pre-flight probe inspects active TCP listeners. If a deadlocked or orphaned tracker process holds the port, it is safely reclaimed.
   - Patches or wraps Uvicorn's reload supervisor to monitor child process liveness (`not self.process.is_alive()`), avoiding the reloader staying alive with zero workers.
4. **Camera Hardware Read Circuit-Breaker (`CaptureReadGuard`)**:
   - Decouples synchronous `cap.read()` native driver calls from the capture loop with a bounded timeout ($2.0\text{s}$) and consecutive empty frame tripping. When a camera freezes post-sleep, the circuit breaker safely trips, releases the underlying capture handle, and executes automatic reconnection without freezing worker threads or blocking graceful server shutdown.
5. **Thread-Safe CameraPool Teardown Invariant**:
   - Ensures `CameraPool.stop_all()` never executes blocking thread joins while holding `_lock`, adhering strictly to Rule 8 & AGENTS.md concurrency invariants.

---

## 1. Architectural Surface Invariants & Quantitative Modularity Budgets

### Quantitative Modularity Ceilings
All modified and newly created files will strictly adhere to the project's modularity guidelines ($\le 350$ lines soft warning, $\le 500$ lines hard ceiling, $\le 10–12$ methods per class, $\le 40$ lines per method):

| Target File | Current Lines | Planned Net Change | Projected Lines | Status | Action |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `dashboard/services/process_supervisor.py` *(New)* | 0 | +190 | ~190 | Healthy ($\le 300$) | Modular Win32 Job Object, Linux `prctl`, and Parent Liveness Watchdog ($\le 8$ methods) |
| `dashboard/services/windows_resilience.py` | 160 | +20 | ~180 | Healthy ($\le 300$) | Expose process tree containment hook for dashboard boot |
| `intelligent_tracker/video/capture_guard.py` *(New)* | 0 | +160 | ~160 | Healthy ($\le 300$) | Non-blocking camera read circuit-breaker & driver unbind watchdog ($\le 6$ methods) |
| `intelligent_tracker/video/capture_worker.py` | 307 | +25 | ~332 | Healthy ($\le 350$) | Integrate `CaptureReadGuard` into `_capture_worker` frame poll |
| `dashboard/camera_pool.py` | 479 | -15 | ~464 | Healthy ($\le 500$) | Fix lock release before thread join in `stop_all` |
| `scripts/run_dashboard.py` | 55 | +55 | ~110 | Healthy ($\le 200$) | Port pre-flight check, Job Object registration, resilient reload loop |
| `tests/test_process_supervisor.py` *(New)* | 0 | +220 | ~220 | Healthy ($\le 300$) | Comprehensive cross-platform tests for Job Object, parent watchdog & port guard |
| `tests/test_capture_circuit_breaker.py` *(New)* | 0 | +200 | ~200 | Healthy ($\le 300$) | Unit tests for camera read timeout, post-sleep recovery & clean driver unbind |

---

## 2. Multi-Phase Roadmap

### Milestone 1: Cross-Platform Process Tree Containment & Parent Liveness Watchdog (Active Execution Target)
**Scope**: Guarantee zero orphaned zombie processes on terminal exit or parent crash across Windows, Linux, and macOS.
- [x] **dashboard/services/process_supervisor.py**: Create cross-platform `ProcessTreeSupervisor` providing:
  - [x] `assign_to_job_object()`: Uses Windows `ctypes` (`CreateJobObjectW`, `SetInformationJobObject`, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, `AssignProcessToJobObject`) to ensure the OS kernel destroys child worker processes if the parent exits. Safely no-ops on Linux/macOS.
  - [x] `set_parent_death_signal()`: Uses Linux `ctypes` (`prctl(PR_SET_PDEATHSIG, signal.SIGTERM)`) on Linux to deliver `SIGTERM` when parent dies. Safely no-ops on Windows/macOS.
  - [x] `start_parent_watchdog(poll_interval=1.0)`: Starts a background daemon thread monitoring parent PID (`os.getppid()`). If parent PID changes (reparenting to PID 1 / `init` on Linux/macOS) or process no longer exists (`psutil.pid_exists` / Win32 `OpenProcess`), logs clean warning and triggers fast graceful exit (`os._exit(0)`).
  - [x] `check_port_available(port: int, host: str = "0.0.0.0") -> bool`: Checks if port is bound.
  - [x] `reclaim_port(port: int, force: bool = False) -> bool`: Identifies owning PID of port; if it is an orphaned python dashboard instance, terminates it cleanly.
- [x] **dashboard/app.py**: Initialize `start_parent_watchdog()` and `set_parent_death_signal()` during application startup inside `lifespan` context.
- [x] **scripts/run_dashboard.py**:
  - [x] Run port pre-flight check before calling `uvicorn.run()`. If port `8000` is held by an orphaned instance, automatically reclaim it with a descriptive console notice.
  - [x] Assign supervisor launcher process to Win32 Job Object with `KILL_ON_JOB_CLOSE`.
- [x] **tests/test_process_supervisor.py**: Add unit tests verifying:
  - [x] Win32 Job Object creation and assignment (mocked and real Windows API when on win32).
  - [x] Parent liveness watchdog detects simulated parent termination and executes callback.
  - [x] Port pre-flight and port reclamation detect listening sockets and handle conflicts.

### Milestone 2: Camera Hardware Read Circuit-Breaker & Lock-Free Pool Teardown (Deferred to Next Milestone)
**Scope**: Eliminate camera driver hangs after sleep/hibernation and guarantee sub-second server shutdown.
- [x] **intelligent_tracker/video/capture_guard.py**: Implement `CaptureReadGuard` decoupling synchronous C++ driver reads:
  - [x] Bounded read execution with timeout (`timeout=2.0s`).
  - [x] Consecutive empty/timeout frame counter tripping circuit-breaker state (`HEALTHY` $\rightarrow$ `STALLED` $\rightarrow$ `RECONNECTING`).
  - [x] Safe driver unbind when kernel graph stalls.
- [x] **intelligent_tracker/video/capture_worker.py**: Wire `CaptureReadGuard` into `_capture_worker()`, preventing DirectShow/V4L2 read calls from blocking thread exit.
- [x] **dashboard/camera_pool.py**: Refactor `stop_all()` to release `self._lock` before waiting on `ThreadPoolExecutor` or worker thread joins, adhering to the Rule: Never hold locks across blocking operations.
- [x] **tests/test_capture_circuit_breaker.py**: Add unit tests verifying camera read timeout tripping, synthetic sleep simulation, and non-blocking teardown under simulated driver deadlocks.

---

## 3. Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Platform | Key Mechanism | Exact Runnable Command | Expected Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **Test Process Supervisor Unit Suite** | Cross-platform | `unittest` | `python -m unittest tests/test_process_supervisor.py` | 100% tests pass (Job Object, parent watchdog, port check) |
| **Simulate Orphaned Port 8000 Reclaim** | Windows & POSIX | Socket pre-flight | `python scripts/run_dashboard.py` (with stale port) | Automatically identifies and reclaims port before launch |
| **Run Full Regression Test Suite** | Headless (`MPLBACKEND=Agg`) | Discover | `python -m unittest discover tests` | All 375+ unit and integration tests pass green |
| **Pre-Commit AST Syntax Check** | Static verification | `ast.parse` | `python -c "import ast; [compile(open(f, encoding='utf-8').read(), f, 'exec') for f in ['dashboard/services/process_supervisor.py', 'scripts/run_dashboard.py']]"` | 0 syntax errors or invalid imports |

---

## 4. Definition of Done (DoD) per Milestone
- **Milestone 1**: `tests/test_process_supervisor.py` passes 100% green; startup port pre-flight cleanly recovers port `8000`; zero orphaned background processes can survive terminal closure.
- **Milestone 2**: `tests/test_capture_circuit_breaker.py` passes 100% green; full test suite (375+ tests) passes; `CameraPool.stop_all()` releases locks before joining threads; changelog and milestone plan updated.

