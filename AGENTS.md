# Intelligent Tracker - Agent Guidelines & Architecture Contract

This file defines repository-wide architecture invariants and execution standards for `intelligent_tracker` (kept strictly under `< 10 KB` so it is never truncated by the 24 KB rule limit). Detailed domain rules load on demand from `.agents/rules/`:
- **Backend, Pipeline, Scheduler & DB**: `.agents/rules/pipeline_and_db_invariants.md` (`trigger: model_decision`)
- **Frontend, Multiview & Node VM Tests**: `.agents/rules/frontend_and_multiview_invariants.md` (`trigger: model_decision`)
- **Cross-Project Ecosystem (`enterprise-website`)**: `.agents/rules/cross_project_ecosystem.md` (`trigger: model_decision`)

---

## 1. Authoritative Architecture & Module Placement ("Split-Before-You-Grow")
- **Blueprints**: Follow `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (Layers 1–5, ADRs 01–06), `docs/architecture/CURRENT_ARCHITECTURE.md`, and `.TODO/integration_hardening_master_roadmap.md`.
- **Dependency Direction**: Never put CV/domain pipeline logic inside `dashboard/` or `cli/`, and never let `intelligent_tracker/` import `dashboard/` or `scripts/`.
- **Live Modularity Audit**: Before planning or editing near-limit modules, run `diagnose.py arch-map --path .` and `diagnose.py audit --path <targets>` to inspect current line counts ($\le 350\text{L}$ soft / $500\text{L}$ hard), class method counts ($\le 12$), and function lengths ($\le 40\text{L}$).
- **Mandatory Placement for New Code**:
  1. **Web Routes & Services**: Place new routes in `dashboard/routers/<domain>.py` ($\le 15–25\text{L}$/route) and logic in `dashboard/services/<domain>_service.py` (never expand `dashboard/app.py` or `dashboard/stream_manager.py`).
  2. **Database Queries**: Place new queries in `intelligent_tracker/repositories/<domain>_repo.py` ($\le 12$ methods/class) and compose via `TrackerDB` (never expand `intelligent_tracker/database.py`). Every write method MUST call `self._conn.rollback()` in `except` before re-raising.
  3. **Frontend JS & CSS**: Place new scripts in `dashboard/static/js/<feature>.js` (multiview under `dashboard/static/js/multiview/`) and styles in `dashboard/static/css/<component>.css` (never expand `dashboard/static/app.js` or `dashboard/static/styles.css`). Reuse existing components (`OverlayControlBar`, `UnifiedCanvasOverlay`) and **ask before creating any new overlapping UI component**.

---

## 2. Python 3.12+ Modernization & Domain Comment Preservation
- **Modern Python 3.10–3.12+ Only**: Zero `from __future__ import ...` (enforced by `tests/test_modernization.py`), zero `six`/`future`/`past` shims, native `class Foo:`, `raise ... from err`, and `collections.abc`.
- **Preserve Domain Math & Reference Comments**: Never delete computer vision docstrings, OpenCV matrix/homography equations, Kalman/IoU formulas, or reference URLs.

---

## 3. Core Runtime, Concurrency & Dual-Clock Invariants
- **Dual-Clock Domain Boundary (`P0-1`)**: Use `time.monotonic()` strictly for `AnalyticsScheduler`, `ProcessingModeService`, FPS pacing, lag deltas, and cooldowns (isolating wall-clock calls in `_wall_now()` helpers when bridging domains); pass Unix epoch `time.time()` (or `base_epoch + video_ts` + `media_offset_sec` in `VideoIndexer`) into `FrameProcessor.step()`, `RSACSchedule`, `TrackerDB`, `EventFTSIndex`, `ConfidenceEngine`, `EventBus`, and `ThumbnailCache.capture_ts_ms`.
- **Pool-Scoped Singletons & Lock Order (`P0-2`, `P0-5`)**: Share one `EventBus`, `WorldGraph`, `ConfidenceEngine`, and `EventFTSIndex` across `CameraPool`, `StreamManager`, and `app.state`. Never nest `ProcessingModeService._lock` and `StreamRecordingController._lock`, and never hold locks across blocking I/O or `thread.join()`.
- **Interruptible Sleeps & Two-Pass Teardown**: Always use `self._stop_event.wait(timeout=delay)` (never `time.sleep()`), broadcast `signal_stop()` across workers before parallel joining, and close owned `TrackerDB` + `EventBus` instances in `StreamManager.stop()` / `PipelineBundle.close()`.

---

## 4. Testing, Verification & Documentation Standards (OS-Agnostic)
- **Virtualenv & Timeout Guard**: Always execute tests and diagnostics via `.venv\Scripts\python.exe` (Windows) or `.venv/bin/python` (POSIX) using `diagnose.py tests` (`180s` timeout guard) and full suite sign-off (`MPLBACKEND=Agg python -m unittest discover tests`).
- **Strict Test Isolation & Lightweight Fixtures**:
  - Never touch live `configs/cameras.json`, `data/*.db`, or `data/reports/`; inject `tempfile.TemporaryDirectory()` and register reverse-order `addCleanup()` teardown (`worker.stop()`, `pool.close()`, `db.close()`).
  - Never run full-video YOLO inference, unmocked `TestClient(app)` lifespans, or hardware camera index `0` in automated tests/probes; use `detector=mock`, `sample_rate=10`, and synthetic 5–10 frame MP4 fixtures.
  - Kill any background test servers (`manage_task kill`) and cancel active test video jobs before ending a turn.
- **Documentation & Changelog**: Keep Sphinx builds warning-free (`python -m sphinx -W --keep-going documentation/ documentation/_build/html/`), record milestones via `diagnose.py changelog add` (never `MIGRATION_LOG.md`), and never commit `file:///` URIs, local absolute paths, or hardcoded `localhost` URLs.
