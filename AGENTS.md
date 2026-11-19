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
- **Strict Test State & Config Isolation**: Tests must NEVER read from or write to live repository config, database, or output paths (`configs/cameras.json`, `data/*.db`, `data/reports/`, or root backup archives) via default constructor arguments. Always pass an isolated `tempfile.TemporaryDirectory()` path to stateful managers (e.g. `CameraPool(config_file=os.path.join(tmpdir, "cameras.json"), autostart=False)`, `TrackerDB(db_path=...)`) and register explicit teardown (`worker.stop()`, `pool.close()`, `db.close()`) via `addCleanup()` in reverse creation order **before** the `TemporaryDirectory` cleanup runs so Windows file-lock `PermissionError` never occurs on `TempDir` removal.
- **Node VM & Test Method Function Budget (<= 40 Lines)**: Keep every test method (including Python tests embedding Node.js `vm.runInNewContext` scripts) strictly `<= 40` lines so `diagnose.py audit` passes on the first run. Split multi-scenario JS assertions (e.g., click-threshold vs. drag-threshold) into separate focused `test_*` methods.
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
4. **New Frontend Scripts & Styles**: Do **NOT** append new feature blocks to `dashboard/static/app.js` or `dashboard/static/styles.css`. Place new frontend modules in `dashboard/static/js/<feature>.js` (with multiview WebSocket transport/canvas logic under `dashboard/static/js/multiview/`, backend multiview services under `dashboard/services/multiview/`, and thin routes under `dashboard/routers/multiview.py`) and component styles in `dashboard/static/css/<component>.css`.
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
  - Reset global FastAPI `app_module` test overrides and call `set_shutting_down(False)` in WebSocket router `TestClient` `setUp`/`addCleanup`, and guard `_conn is not None` in DB resolvers so closed test DBs or shutdown flags cannot leak across `unittest discover` order.
  - Mount static WebSocket/HTTP routers (`/ws/multiview`) before wildcard routers (`/ws/{camera_id}`) in `dashboard/app.py` and verify router wiring against the assembled `dashboard.app.app` (not only isolated `FastAPI()` instances).
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

## 12. Step 5 Runtime & Test Fixture Invariants
- **`PipelineConfig` & `ActiveLearningTriage`**: `PipelineConfig` uses `detector_confidence` and `detector_classes`; `ActiveLearningTriage` debounce must treat `last=None` as eligible so `timestamp=0.0` offline frames are not suppressed.
- **`ScenarioManager` & `TrackerDB` Signatures**: `ScenarioManager` uses `config_path`, `save_zone`, and `save_tripwire`; `TrackerDB` uses `set_rsac_rule(allowed_categories=...)`, `get_review_item(item_id)`, `add_entity()`, and `add_sighting()` (not `add_zone`, `add_rsac_rule`, `get_review_queue`, or `upsert_entity`).
- **Offline Video Test Fixtures**: `VideoIndexer` defaults to `reid_name='color'`, and `MockDetector` ignores class filters unless `boxes=[]` is configured.
- **`StreamSubscriberRegistry` & `StreamWorker` Test Invariants**:
  - Keep `StreamSubscriberRegistry` `<= 12` methods by storing simple boolean flags (`is_hibernating`) as plain attributes on the registry while exposing property getters/setters on `StreamSubscriberMixin`.
  - When testing `StreamWorker` mode switching or selective JPEG encoding in isolation, seed `_latest_raw_jpeg` and `_latest_jpeg` on the host unless testing cold-start cache seeding, because `StreamWorker` encodes both when caches are `None`.
- **Dashboard JS, Fetch & HTML Asset Regex Invariants**:
  - Match real HTML asset tags with negative lookbehind `(?<!data-)src=` in static/template tests so lazy-loaded `data-src=` attributes do not trigger false missing-asset failures.
  - Shared `fetch` deduplication helpers (e.g., in-flight request maps) MUST return `resp.clone()` before callers invoke `.json()` or `.text()` to avoid `"body stream already read"` errors across concurrent consumers.
  - Node VM tests exercising `dashboard/static/js/studio.js` incremental/delta list rendering must stub DOM creation/diff hooks (`document.createElement` with `children: []` and `appendChild`, `innerHTML`, row element stubs, and `StudioOverlays.renderScenarioListUI`/`renderTopologyLinksUI`) cleanly in small (`<= 40L`) focused test helpers, and measure BEV minimap timer activity via delta renders across `_tickIntervals()` rather than absolute count (since `initStudio` performs one initial render).
  - When testing async `fetch().then(r => r.json())` flows in Node VM without timers, flush multiple microtask ticks (or await the returned init promise) so `resp.json()` resolves before asserting DOM updates.
- **Per-File Budget Note**: `intelligent_tracker/journey_segmenter.py` has a `< 160` line cap (`tests/test_step4_preflight_budgets.py`), `StreamPoolCoordinator` has a `< 240` line cap (`tests/test_dashboard_di.py`), and `dashboard/services/stream_worker.py` has a `<= 285` line cap (`tests/test_step3_architecture_budgets.py`). Verify custom line budgets with `diagnose.py audit --max-lines <N>` immediately after editing constrained modules.
- **Processing Mode DI & Sign-Off Invariants**:
  - Import `get_processing_mode_service` lazily inside `StreamManager.__init__` and `StreamPoolCoordinator.__init__` rather than at module top-level, because `processing_mode_service.py` imports `video_analytics_service`/`dependencies` which transitively imports `CameraPool` -> `StreamManager`.
  - Inject `mode_service_getter` into `StreamRecordingController` so standalone unit tests remain isolated while `StreamManager` shares its `ProcessingModeService`.
  - When seeding `CameraPool` in isolated tests with stubbed streams, mark cameras `enabled=False` in the temp `cameras.json` so `load_cameras()` does not open real `TrackerDB` SQLite handles that block Windows `TemporaryDirectory` cleanup.
  - Always run the full `python -m unittest discover tests` suite at child-plan sign-off to catch cross-step modularity budget tests such as `tests/test_dashboard_di.py`.
- **Multiview Socket Budget, Viewing ≠ Analytics & HTML Shell Ceilings**:
  - Each SPA tab uses at most `1` `/ws/multiview` socket + `1` 1x1 MJPEG `/stream/{id}` (or `<= 4` MJPEG sockets on `2x2` pages during 3-failure degraded fallback), sending `unsubscribe_all` when leaving the grid and closing after 30 s idle or on `pagehide`.
  - Grid `/ws/multiview` subscriptions wake capture via `annotated=False` subscriber leases and share encoded `ThumbnailCache` tiers per camera/width, without ever altering `ProcessingModeService.should_run_vision_step()` (`armed` cameras stay awake except under `paused`).
  - Keep `dashboard/static/index.html < 180` lines, `dashboard/static/partials/tabs/live.html < 220` lines, and `dashboard/static/js/processing_mode.js < 220` lines.
  - Wrap native WebIDL timer methods (`window.setTimeout`, `window.clearTimeout`) in arrow functions (`(fn, ms) => setTimeout(fn, ms)`) rather than storing bare function references on class instances (`TypeError: Illegal invocation` in V8).

## 13. Async Pipeline, Warmup & Test Synchronization Invariants
- **Standalone `StreamManager` Hibernation (`focus_only`)**: `ProcessingModeService.should_hibernate_camera()` must return `True` when `not in_camera_pool` and `subscriber_count <= 0` in `focus_only` mode; in `StreamWorker._should_hibernate()`, distinguish `frame_count` from `subscriber_count`.
- **Async `StreamWorker` `step_done` Test Sync**: Because `StreamWorker.run()` dispatches `FrameProcessor.step()` asynchronously via `AsyncInferenceWorker`, tests that set `_stop_event` inside `_process_single_frame` must wait on a `step_done` event before asserting `mock_proc.step.assert_called_once()`.
- **`asyncio.Event` Loop Binding (Python 3.12+)**: Construct `asyncio.Event()` inside the active `asyncio.run(...)` coroutine in unit tests rather than in `setUp()` or outside the loop, so it is never bound to a closed event loop across sub-runs.
- **`warmup_timeout=None` Scaling**: `VideoSource` and `CaptureReadGuard` default `warmup_timeout=None` to scale dynamically with `read_timeout` (`read_timeout * 2.5`) so fast unit tests with small `read_timeout` (e.g., `0.1s`) are not stretched to `5.0s`.
- **`FrameProcessor.step` Spy Filtering**: Class-level `FrameProcessor.step` spies in batch tests must filter by `self.db` to avoid cross-talk from background/daemon stream threads.
- **Zero Hardcoded `'cam_01'` Focus/Stream Defaults**: Never default `ProcessingModeService.focused_camera_id` or frontend stream/WebSocket/studio/AI-config fallbacks to `'cam_01'` when `cameras.json` uses dynamic camera IDs. `ProcessingModeUI.isValidCameraId()` must return `false` while `availableCameras` is `null` (before `/api/cameras` loads), and stream/WS/studio attach helpers must guard on a resolved non-empty camera ID rather than firing requests to `/stream/cam_01` or `/ws/cam_01`.
- **Grid Teardown & MJPEG Socket Budget**: Always call `LivePlayer.detachGridStreams()` before `innerHTML` grid teardown and cap active MJPEG grid tiles per page (via `GridPagination`) so HTTP/1.1 browser connection pools are never exhausted.
- **Fast-Fail `_ready_event`, Error Hibernation & `MagicMock` Stubs**: `VideoSource._capture_worker` must set `self._ready_event.set()` in its `finally` block so `wait_ready()` unblocks immediately on fast-failing file sources; `StreamWorker.run()` must suppress idle hibernation (`hib_frames = 0`) while `consecutive_errors > 0`. In `StreamWorker` tests, never pass `name=...` to `MagicMock(...)` and explicitly set `_processing_mode_service = None` so hibernation comparisons do not evaluate truthy child mocks.
- **`interactive_canvas.js` Budget & Tag Modal Fallback**: Keep `dashboard/static/interactive_canvas.js < 240` lines (`test_step3_tag_modal_integration.py`); centralize scale-factor resolution in `getActiveScales()` and keep the `live-stream-img || video-stream` element fallback for legacy Node VM tests.
