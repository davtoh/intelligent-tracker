# Intelligent Tracker - Agent Guidelines & Modernization Rules

This file documents persistent instructions, modernization principles, and architecture rules for AI coding assistants working in this repository.

## 1. Python Modernization & Decrufting Standards
All codebase additions and refactors MUST strictly follow modern Python 3.10–3.12+ idioms:
- **Zero `__future__` Imports**: Never use `from __future__ import ...` (including `annotations`, `division`, `print_function`, `absolute_import`). The project strictly targets Python 3.10–3.12+, where type unions (`|`), built-in generics (`list[T]`, `dict[K, V]`), and mathematical operations are natively supported without postponed stringification overhead or legacy shims. Automated enforcement is maintained via `tests/test_modernization.py`.
- **No Obsolete Shims**: Never import `builtins.object`, `past.builtins.basestring`, `past.utils.old_div`, or `six` (`reraise`, `with_metaclass`, `moves`).
- **Clean Class Declarations**: Never write `class Foo(object):`. Use standard `class Foo:`. For metaclasses, use `class Foo(metaclass=Meta):`.
- **Modern Exception Chaining**: Use native `raise NewException(...) from err` rather than custom reraise helpers.
- **Standard String & Path Types**: Use native `str` instead of `basestring`. Use standard `pathlib.Path` or `os.path`.
- **Collections ABCs**: Always import abstract collections from `collections.abc` (e.g. `MutableMapping`, `MutableSet`, `Iterable`), never from `collections`.
- **Lean Dependencies**: Maintain a minimal dependency footprint without legacy bridging packages (`future`, `six`).

## 2. Comment & Mathematical Formula Preservation
- **Preserve Domain Comments**: Never strip or summarize computer vision docstrings, mathematical proofs, camera matrix coordinate transformations, or algorithm rationale.
- **Maintain Algorithm Explanations**: OpenCV matrix calculations, moment division formulas, IoU and Kalman kinematic states must retain their original mathematical annotations.

## 3. Testing & Verification Standards (OS-Agnostic)
- Always run the full test suite in headless mode using cross-platform commands (with `MPLBACKEND=Agg` set in the environment):
  ```bash
  python -m unittest discover tests
  ```
- Ensure 100% green test passes across all unit and integration tests.
- When adding new modules or fixing bugs, add corresponding unit tests in `tests/test_<module>.py`.
- **Strict Test State & Config Isolation**: Tests must NEVER read from or write to live repository config, database, or output paths (`configs/cameras.json`, `data/*.db`, `data/reports/`, or root backup archives) via default constructor arguments. Always pass an isolated `tempfile.TemporaryDirectory()` path to stateful managers (e.g. `CameraPool(config_file=os.path.join(tmpdir, "cameras.json"), autostart=False)`, `TrackerDB(db_path=...)`) and register cleanup via `addCleanup()` or `tearDown()`.
- Never leave temporary `scratch/` directories or browser profiles inside the repository root.

## 4. Documentation Standards (OS-Agnostic)
- Keep Sphinx documentation up-to-date in `documentation/` and ensure clean builds with zero warnings:
  ```bash
  python -m sphinx -W --keep-going documentation/ documentation/_build/html/
  ```
- Maintain `CHANGELOG.md` (recording completed milestones via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add`) with detailed records of code changes, architectural decisions, and verification results.
- Never embed `file:///` URIs, machine-local absolute paths, OS-locked virtualenv binary paths, or hardcoded `localhost` URLs inside committed plans or documentation.

## 5. Frontend, CSS & Specificity Standards
- **Strict Avoidance of `!important`**: Never use `!important` in production stylesheets. `!important` breaks the natural CSS cascade, prevents responsive theme overrides, breaks fullscreen pseudo-classes (`:fullscreen`), and creates compounding specificity debt that downstream components cannot override.
- **Natural Specificity Hierarchy**: Structure selectors using clean structural cascading (e.g. `.video-card:fullscreen .video-container`), pseudo-classes (`:fullscreen`, `:hover`, `:focus-visible`), or CSS custom properties (variables) rather than brute-forcing specificity with `!important`.
- **Contained Overflow & Text Truncation**: All flexible headers, labels, and title spans must specify `min-width: 0`, `overflow: hidden`, and `text-overflow: ellipsis` along with descriptive `title` attributes to prevent unbounded string expansion from blowing out parent grid or flex layouts.
- **Defensive Spacing & Structural Separation**: Primary flex containers, navigation bars, and action clusters must define explicit proportional gaps and margins (minimum 8px between internal buttons, 16px–24px between major layout sections). Controls must never sit flush against adjacent groups with 0px gap.
- **Zero Collision & Overlap Guarantee**: Controls (scroll buttons, dropdown triggers, action pills, badges, modals) must never collide, overlap, or visually occlude sibling components. Touch targets must satisfy WCAG AA minimum sizing (>= 24px, recommended >= 32px-44px for primary controls).
- **Strict Viewport Containment**: Enforce zero document horizontal overflow (`max-width: 100vw; overflow-x: clip;`). Every flexible container and child must use defensive sizing (`min-width: 0; max-width: 100%`) so content scales, wraps, or scrolls internally without escaping viewport bounds or generating unwanted root horizontal scrollbars.
- **Resilient Directional Control States**: Directional navigation arrows and scroll buttons must accurately reflect viewport edge proximity. When computing boundary states, logic must account for container padding, border widths, and CSS scroll-snap resting alignments (`scroll-snap-align`) rather than assuming exact zero offsets (`scrollLeft <= 0`).

## 6. Core Coding Principles & Quantitative Modularity Budgets
All new code and refactors must adhere to the 10 Core Coding Principles (**SRP, DRY, KISS, Descriptive Naming, Comments for the "Why", Consistent Style, Error Handling & Robustness, Testing & Verification, Version Control Hygiene, and Security First**) and the following structural budgets:

| Code Element | Healthy Target | Soft Warning (Refactor Trigger) | Hard Ceiling (Mandatory Split) | Required Action |
| :--- | :--- | :--- | :--- | :--- |
| **Source File** (`.py`, `.js`, `.css`) | 150 – 300 lines | **350 lines** | **500 lines** | Extract domain submodules (`routers/`, `services/`, `repositories/`, `static/js/`). |
| **Class** | 50 – 180 lines | **10 methods** (or 200 lines) | **12 methods** (or 300 lines) | Decompose using composition, focused domain services, or cohesive mixins. |
| **Function / Method** | 10 – 25 lines | **30 lines** | **40 lines** | Extract pure helper functions; flatten nested conditionals. |
| **Route / Endpoint** | 5 – 15 lines | **15 lines** | **25 lines** | Keep handlers thin: parse request, invoke a service, and return response. |

## 7. Monolith Freeze & Strangler-Fig Architecture Map
Most prior monoliths (`styles.css`, `database.py`, `app.py`, `geometry.py`, `detectors.py`, `core.py`, `events.py`, `stream_manager.py`, `tracker.py`) have been decomposed into packages (`repositories/`, `routers/`, `services/`, `events/`, `tracker/`, `detectors/`, `geometry/`). The remaining files currently at or above budget are under an active **Monolith Freeze**:
- **Hard Ceiling (>= 500 lines)**: `intelligent_tracker/high_objects.py` (523 lines; `Scene` 25 methods)
- **Soft Warning / Heavy Classes (350–499 lines or > 12 methods)**: `dashboard/static/js/video_jobs.js` (493 lines), `intelligent_tracker/batch.py` (485 lines), `dashboard/static/js/video_library.js` (471 lines), `intelligent_tracker/interactive.py` (451 lines), `scripts/cdp_inspect.py` (436 lines), `intelligent_tracker/matching/gallery.py` (425 lines), `intelligent_tracker/rsac.py` (412 lines, `RSACManager` 14 methods), `dashboard/static/video_scrubber.js` (388 lines), `dashboard/static/js/scrubber_overlay.js` (372 lines), `dashboard/static/camera_manager.js` (366 lines), `dashboard/static/js/overlay_layers.js` (362 lines), `dashboard/static/app.js` (355 lines); heavy classes <= 350L: `TailItem` (20 methods), `Group` (19), `EventFigure` (19), `CaptureReadGuard` (16), `CameraDeviceHandler` (15), `GroupMutationMixin` (15), `FrameProcessor` (14)

### Mandatory Placement for New Features ("Split-Before-You-Grow")
1. **New Web Routes & API Endpoints**: Do **NOT** add new endpoints directly into `dashboard/app.py`. Place new route handlers in `dashboard/routers/<domain>.py` (using FastAPI `APIRouter`) and business logic in `dashboard/services/<domain>_service.py`, then mount the router in `dashboard/app.py`.
2. **New Database Queries & Tables**: Do **NOT** add new methods directly into `TrackerDB` inside `intelligent_tracker/database.py`. Create focused domain repositories or query mixins in `intelligent_tracker/repositories/<domain>_repo.py` ($\le$ 10–12 methods per class) and compose or re-export them via `TrackerDB` so existing callers remain unbroken.
3. **New Stream / Pipeline Logic**: Do **NOT** expand `dashboard/stream_manager.py`. Extract focused collaborator classes (e.g. `dashboard/services/stream_lifecycle.py`, `dashboard/services/frame_Overlay.py`).
4. **New Frontend Scripts & Styles**: Do **NOT** append new feature blocks to `dashboard/static/app.js` or `dashboard/static/styles.css`. Place new frontend modules in `dashboard/static/js/<feature>.js` and component styles in `dashboard/static/css/<component>.css`.
5. **Decomposing Existing Monoliths**: When executing a dedicated refactoring milestone, use the `/refactor-monolith` skill and preserve 100% of existing public imports via `__init__.py` or facade re-exports.

## 8. Thread Safety & Task Shutdown Invariants
- **Interruptible Worker Sleeps**: Never use uninterruptible `time.sleep()` in long-running background loops, worker threads, or reconnection backoffs. Always use kernel event waits: `self._stop_event.wait(timeout=delay)`. When shutdown is requested, setting `_stop_event` must wake threads in $< 10\text{ms}$.
- **Two-Pass Non-Blocking Teardown**: When managing multiple child workers or streams, implement a two-pass teardown:
  1. *Pass 1 (Broadcast)*: Signal all child tasks/threads to stop simultaneously (`signal_stop()`).
  2. *Pass 2 (Parallel Join)*: Join/await workers concurrently (`ThreadPoolExecutor` or `asyncio.gather`) with bounded timeouts. Multi-worker teardown must scale in $O(1)$ time: $\max(t_1, \dots, t_N)$ rather than $\sum t_i$.
- **Zero Orphaned Workers**: Every component that spawns threads or asyncio background tasks (`EventBus`, `StreamManager`, `VideoSource`, `TelemetrySampler`) must provide a paired `stop()` method, and parent lifecycles must explicitly invoke it.
- **Deterministic SQLite & EventBus Teardown**: `StreamManager.stop()` and `PipelineBundle.close()` must close owned `TrackerDB` handles and stop both primary and fallback `EventBus` instances (which must call `.start()` on creation) to prevent Windows SQLite file locks.
- **Async Event Loop Protection**: Never execute heavy synchronous hardware driver unbinds or process joins directly on the main asyncio event loop. Offload them via `asyncio.to_thread()`.
- **Fail-Safe Watchdog**: Mission-critical server processes must include a background watchdog timer during shutdown to prevent deadlocks from uncooperative C/C++ kernel drivers.

## 9. Branch Coverage & Static Symbol Resolution Invariants
- **Exhaustive Branch Testing (`if/elif/else`)**:
  - Tests must never cover only the "happy path" `if` condition. When introducing branching logic with fallback dependencies, conditional coordinators, or error branches, add explicit unit tests exercising every `elif` and `else` branch.
  - Specifically test fallback configurations (e.g., primary pool absent $\rightarrow$ single-stream fallback branch executed).
- **Global Test Fixture & Import Hygiene**:
  - Reset global FastAPI `app_module` test overrides in `tearDownClass` and guard `_conn is not None` in DB resolvers so closed test DBs cannot leak across `unittest discover` order.
  - Preserve `try/except ImportError` optional-dependency availability probes (`zlib`, `scipy`, `picamera`) when cleaning `arch-map` unused-import alerts, and keep `.. automodule::` directives in one canonical `.rst` file so `sphinx -W` stays warning-free.
- **Pre-Commit Static Symbol Verification (AST Check)**:
  - Whenever code is added or modified, verify that all symbols, modules, and type references are explicitly imported at the top of the file.
  - In environments without active linter daemons, run a fast AST compile check before marking tasks complete:
    ```bash
    python -c "import ast; [compile(open(f, encoding='utf-8').read(), f, 'exec') for f in ['<modified_files>']]"
    ```
  - Never assume a branch is valid simply because the main test suite passed without error.

## 10. Video Studio Processing, Concurrency & Resource Safety
- **Lightweight Test Fixtures for Verification**:
  - NEVER run full-video YOLOv8 inference or unthrottled transcode jobs during automated testing or verification.
  - Verification suites and CDP tests MUST pass `detector=mock` and `sample_rate=10` or use synthetic 5–10 frame test fixtures in `tests/test_video_jobs.py` to prevent CPU/GPU starvation.
- **Mandatory Server & Test Job Cleanup**:
  - If `scripts/run_dashboard.py` is started as a daemon for verification, the executing agent MUST terminate the background task (`manage_task kill`) and cancel any active test jobs via `POST /api/videos/jobs/{job_id}/cancel` before closing the turn.
- **Persistent Occurrence Reports**:
  - Occurrence indexing reports generated by `VideoIndexer` must be saved to disk (`data/reports/{video_filename}_report.json`) or `TrackerDB` so they survive server restarts and browser reloads.
- **Cross-Video View Isolation**:
  - In `dashboard/static/js/video_batch.js` and `dashboard/static/js/video_library.js`, all async job listeners (`job-started`, `job-update`, `job-finished`) must check `currentBatchFilename === job.filename` before updating DOM containers or buttons.
- **Transcode Player Auto-Switch**:
  - When `_h264.mp4` conversion finishes and `currentViewedFilename` matches the original file, automatically switch `videoPlayer.src` to the new web-compatible file.

## 11. Target World Architecture & Master Planning Contract
- **Authoritative Blueprint**: All new modules, refactors, and feature plans MUST follow the layered architecture, folder ownership (`intelligent_tracker/pipeline/`, `intelligent_tracker/world/`, `intelligent_tracker/memory/`), and ADRs in `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`.
- **Master Roadmap Sequencing**: Execute and plan major architectural changes one step at a time following `.TODO/world_architecture_master_roadmap.md` (Steps 1–6). Never bypass `intelligent_tracker/` to put business or CV pipeline logic inside `dashboard/` or `cli/`, and never let `intelligent_tracker/` import `dashboard/` or `scripts/`.
- **Pre-Plan Static Architecture Check**: Before evaluating or drafting any Step plan, run the unified architecture mapper (`diagnose.py arch-map --path .`) to verify current modularity budgets, route/CLI parity, coupling, and unused imports.
