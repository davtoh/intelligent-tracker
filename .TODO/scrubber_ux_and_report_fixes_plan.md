# Video Studio Scrubber UX, Transcode Rollback & Report Lifecycle Plan

## 1. Empirical Symptom-to-Root-Cause Matrix (`/app-debugger` Phase 1B–3)

| # | Observed Symptom | Empirical Evidence | Root Cause Analysis | Target Files & Lines | Verification Command |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **"More conversion actions" (`▾`) menu renders underneath sibling video cards** | In `.video-recordings-list`, opening `.video-action-menu` (`z-index: 30`) on card $i$ causes card $i+1$ to paint over the menu button `↺ Re-convert`. | Every `.video-file-card` includes `.glass-panel` (`dashboard/static/css/tokens.css#L57-L60`), which applies `backdrop-filter: blur(14px)`. Per CSS Filter Effects Level 2, `backdrop-filter` creates an isolated stacking context at `z-index: auto`. Later DOM siblings paint above earlier siblings and all their descendants regardless of child `z-index: 30`. | `dashboard/static/css/scrubber.css#L181-L278`, `dashboard/static/js/video_library.js#L46-L115` | `python -m unittest tests/test_scrubber_ux_fixes.py` |
| **2** | **No UI or API control to delete unwanted "Occurrence Indexing Report" runs** | `video_report_store.py` only supports `save_report_run` and `list_report_runs`. `#batch-report-run-select` has no per-run delete or clear-all action. | Missing `delete_report_run` / `clear_report_runs` persistence primitives, `DELETE` API endpoints, and report header action buttons. Additionally, `video_batch.js` is at 498 lines (hard ceiling 500L) and must be decomposed before adding UI controls. | `dashboard/services/video_report_store.py#L219-L281`, `dashboard/routers/video_jobs.py#L305-L345`, `dashboard/static/js/video_batch.js#L103-L203` | `python -m unittest tests/test_video_report_deletion.py` |
| **3** | **Cancelling a `force=true` fresh transcode destroys the previously working `_h264.mp4`** | Running Re-convert (`force=true`) and cancelling deletes `{stem}_h264.mp4`, leaving neither new nor old H.264 file. | `VideoTranscodeService.transcode_to_h264_async` runs `ffmpeg -y ... output_path` directly on the destination path, immediately truncating the prior working `_h264.mp4`, and `os.remove(output_path)` deletes it on cancel (`video_transcoder.py#L157-L287`). | `dashboard/services/video_transcoder.py#L110-L295`, `dashboard/static/js/video_library.js#L278-L304` | `python -m unittest tests/test_transcode_atomic_rollback.py` |
| **4** | **On `...G94106186.mp4`, Run 1 & Run 3 align only on original (`2688×1520`) while Run 2 aligns only on converted `_h264.mp4` (`1920×1086`)** | Inspection of `data/reports/*G94106186*` shows Run 1 (`run_6703328d`) & Run 3 (`run_0eb3f6f7`) have `filename: "...G94106186.mp4"` (`2688×1520`), while Run 2 (`run_940ec433`) has `filename: "...G94106186_h264.mp4"` (`1920×1086`), and all three have `source_resolution: null`. | Runs created prior to `source_resolution` persistence store `source_resolution: null`. When `source_resolution` is null, `ScrubberOverlayRenderer.resolveScaleFactors` falls back to `[videoWidth, videoHeight]` of the currently loaded video element, mis-scaling `2688×1520` boxes on `1920×1086` playback (and vice versa). Also `scrubber_overlay.js#L307` falls back to `getPrimaryLayer()?.sourceResolution` across distinct layers. | `dashboard/services/video_report_store.py#L219-L281`, `dashboard/static/js/scrubber_overlay.js#L303-L315`, `dashboard/static/js/scrubber_overlay_renderer.js#L88-L100` | `python -m unittest tests/test_report_resolution_backfill.py` |
| **5** | **Clicking any video card or switching original/`_h264` resets `scrubber-timeline-slider` to `0` regardless of `scrubber-tab-policy`** | `loadVideoIntoPlayer` (`video_scrubber.js#L307-L310`) and `onVideoLoaded` (`#L416-L420`) unconditionally set `videoPlayer.currentTime = 0` and `timelineSlider.value = 0`. | `tabPolicy` (`auto-resume`, `keep-paused`, `reset`) is only checked inside `onTabEnter()`, never during `loadVideoIntoPlayer()` or `onVideoLoaded()`, and no per-recording timestamp state is stored. | `dashboard/static/video_scrubber.js#L297-L436` | `python -m unittest tests/test_scrubber_ux_fixes.py` |

---

## 2. 3-Tier Architectural Proposition (`/frontier-architect` Phase 3)

### Tier 1: Pragmatic Baseline
- Patch `z-index` on `.video-file-card:hover`, delete report JSON entries in-place without alias cleanup, copy `.bak` files before transcode, manually delete old runs in UI, and pass `currentTime` only when clicking `Switch to H.264`.
- *Trade-off*: Leaves keyboard/click-opened menus behind hovered cards, misses alias report files (`_h264.mp4_reports.json`), and still loses scrubber position when clicking between video cards in the library.

### Tier 2: Frontier SOTA (Recommended Default)
- **Natural Stacking Context Elevation**: Give `.video-file-card` `position: relative` and elevate `.video-file-card:has(.video-action-menu:not([hidden])), .video-file-card.menu-open { z-index: 25; }` with zero `!important`, while splitting `scrubber.css` (473L $\rightarrow$ $\le 340$L + `scrubber_overlays.css`) to honor modularity budgets.
- **Transactional Staging Transcode & Self-Healing Resolution Backfill**: Write FFmpeg output to an isolated `.part.mp4` staging file and `os.replace()` into `output_path` strictly on clean completion (`returncode == 0` and not cancelled), preserving any pre-existing `_h264.mp4` untouched on cancellation/error. Automatically probe and backfill missing `source_resolution` from each run's recorded `filename` (`2688×1520` vs `1920×1086`) in `video_report_store.py` so legacy Run 1, Run 2, and Run 3 all align accurately on both original and converted playback.
- **Alias-Complete Report Deletion & Policy-Governed Scrubber Memory**: Provide `DELETE /api/videos/{filename}/reports/{run_id}` and `DELETE /api/videos/{filename}/reports` cleaning across all recording aliases, extract `dashboard/static/js/video_batch_reports.js` from the 498-line `video_batch.js`, and persist per-recording playback timestamps keyed by canonical recording stem (`getBaseStem(filename)`) governed by `#scrubber-tab-policy`.

### Tier 3: Novel 0-to-1 Paradigm (Moonshot)
- Normalize all persisted bounding boxes into resolution-independent `[0.0, 1.0]` UV coordinates at write time with IndexedDB client-side frame caches and WebCodecs frame-accurate scrubbing.
- *Trade-off*: Breaking schema migration for external consumers of `*_detections.json`; Tier 2's self-healing `source_resolution` backfill achieves identical visual alignment with zero schema breakage.

---

## 3. Modularity & Surface Invariants ("Split-Before-You-Grow")

To strictly enforce `AGENTS.md` Section 6 ($\le 350$ lines soft trigger, $\le 500$ lines hard ceiling, $\le 40$ lines per function):
1. **`dashboard/static/js/video_batch.js` (currently 498 lines)**: Extract report card rendering, run history dropdown, and run deletion/clear-all handlers into `dashboard/static/js/video_batch_reports.js` ($\sim 210$ lines), reducing `video_batch.js` to $\sim 310$ lines.
2. **`dashboard/static/css/scrubber.css` (currently 473 lines)**: Extract overlay layer toolbar and batch report header/action styles into `dashboard/static/css/scrubber_overlays.css` ($\sim 150$ lines, imported in `dashboard/static/styles.css`), reducing `scrubber.css` to $\sim 335$ lines.
3. **`dashboard/routers/video_jobs.py` (currently 347 lines)**: Keep $\le 345$ lines by keeping route handlers thin (5–12 lines) and placing alias-aware deletion and resolution backfill logic in `dashboard/services/video_report_store.py`.

---

## 4. Multi-Phase Execution Roadmap

### Milestone 1: Transactional Force-Transcode Rollback, Self-Healing Run Resolution & Report Deletion API *(Active Execution Target)*
- [x] **dashboard/services/video_transcoder.py**: Update `transcode_to_h264` and `transcode_to_h264_async` to write FFmpeg output to a temporary staging file (`{output_path}.part.mp4`), clean up only the staging file on cancellation or non-zero exit code (preserving any existing `output_path` intact), and atomically promote via `os.replace(staging_path, output_path)` only upon verified completion.
- [x] **dashboard/services/video_report_store.py**: Add `_infer_source_resolution_for_filename(filename)` using `VideoTranscodeService.probe_video` to automatically resolve and backfill missing `source_resolution` on legacy runs/streams (healing Run 1 `2688×1520`, Run 2 `1920×1086`, and Run 3 `2688×1520`), and add `delete_report_run(filename, run_id)` and `clear_report_runs(filename)` across all alias `*_reports.json` and `*_detections.json` files.
- [x] **dashboard/routers/video_jobs.py**: Expose `DELETE /api/videos/{filename}/reports/{run_id}` and `DELETE /api/videos/{filename}/reports` endpoints while keeping `video_jobs.py` under 350 lines.
- [x] **tests/test_transcode_atomic_rollback.py**: Add unit tests verifying that cancelling or failing a `force=true` transcode leaves the pre-existing `_h264.mp4` file intact and non-empty, while successful completion atomically replaces it.
- [x] **tests/test_video_report_deletion.py**: Add unit and API tests covering per-run deletion, clear-all deletion across original/`_h264` aliases, and automatic `source_resolution` backfill for legacy runs with `source_resolution: null`.

**Milestone 1 Definition of Done (DoD)**:
- [x] All unit tests in `tests/test_transcode_atomic_rollback.py` and `tests/test_video_report_deletion.py` pass (`MPLBACKEND=Agg python -m unittest`).
- [x] Legacy `data/reports/*G94106186*` runs return accurate `source_resolution` (`[2688, 1520]` for Runs 1 & 3; `[1920, 1086]` for Run 2).
- [x] AST symbol check and modularity line budgets ($\le 350$ lines) verified.

---

### Milestone 2: Natural Card Stacking Context, Report Deletion UI & Modularity Decomposition *(Deferred to Next Turn)*
- [x] **dashboard/static/css/scrubber_overlays.css**: Extract overlay layer toolbar and batch report header/delete button styles from `scrubber.css` so both CSS files remain under 350 lines.
- [x] **dashboard/static/css/scrubber.css**: Add `position: relative` to `.video-file-card` and natural stacking elevation `.video-file-card:has(.video-action-menu:not([hidden])), .video-file-card.menu-open { z-index: 25; }` (zero `!important`).
- [x] **dashboard/static/styles.css**: Import `css/scrubber_overlays.css` after `css/scrubber.css`.
- [x] **dashboard/static/js/video_library.js**: Toggle `.menu-open` on the parent `.video-file-card` when `.video-action-menu` opens/closes, and preserve paired H.264 switch controls when a `force=true` re-convert job is cancelled.
- [x] **dashboard/static/js/video_batch_reports.js**: Extract report card rendering, run history switcher, and new `🗑️ Delete Run` / `🧹 Clear All` buttons from `video_batch.js`, wiring `DELETE /api/videos/{filename}/reports/{run_id}` and `DELETE /api/videos/{filename}/reports` with `OverlayLayers` and `ScrubberOverlay` synchronization.
- [x] **dashboard/static/js/video_batch.js**: Delegate report view rendering and deletion lifecycle to `VideoBatchReports`, reducing `video_batch.js` below 350 lines.
- [x] **dashboard/static/index.html**: Include `/static/js/video_batch_reports.js` before `/static/js/video_batch.js`.

**Milestone 2 Definition of Done (DoD)**:
- [x] `.video-action-menu` renders above sibling `.video-file-card` elements in live/headless CDP (`document.elementFromPoint` hits `.btn-reconvert-video`, `occludedBySibling === false`).
- [x] Per-run delete and Clear All buttons remove runs from disk, update the History dropdown, and remove deleted layers from `#scrubber-overlay-layers` and the canvas.

---

### Milestone 3: Layer-Isolated Coordinate Scaling & Policy-Aware Scrubber Timeline Persistence *(Deferred to Next Turn)*
- [x] **dashboard/static/js/scrubber_overlay.js**: Pass `layer.sourceResolution` directly to `renderer.resolveScaleFactors` in `render()` without cross-contaminating from `getPrimaryLayer()?.sourceResolution` when multiple runs with different resolutions (e.g., `2688×1520` and `1920×1086`) are active concurrently.
- [x] **dashboard/static/video_scrubber.js**: Persist per-recording playback timestamps (`savedPlaybackByStem` keyed by canonical recording stem `getBaseStem(filename)`) and honor `#scrubber-tab-policy` (`auto-resume`, `keep-paused`, `reset`) inside `loadVideoIntoPlayer` and `onVideoLoaded` so switching between original/`_h264` pairs or clicking between recordings preserves the scrubber timeline slider position unless `reset` is selected.
- [x] **tests/test_scrubber_ux_fixes.py**: Add comprehensive regression tests verifying CSS stacking rules, multi-resolution concurrent layer scaling (`2688×1520` + `1920×1086`), and `scrubber-timeline-slider` preservation across video switches under all three `scrubber-tab-policy` modes.

**Milestone 3 Definition of Done (DoD)**:
- [x] Full test suite passes (`MPLBACKEND=Agg python -m unittest discover tests`).
- [x] Live/headless CDP verification confirms `scrubber-timeline-slider` retains position when switching between original and `_h264` or across recordings according to `#scrubber-tab-policy`, and Run 1, Run 2, and Run 3 overlay accurately on both original and converted video files.

---

## 5. Executable Scenario Combinations Matrix

| Scenario | Inputs / Mode | Expected Outcome | Runnable Verification Command |
| :--- | :--- | :--- | :--- |
| **1. Action Menu Z-Index Above Sibling Cards** | Open `.btn-action-menu-toggle` on card #1 | `.video-action-menu` has `z-index` above card #2 (`occludedBySibling === false`) | `MPLBACKEND=Agg python -m unittest tests/test_scrubber_ux_fixes.py` |
| **2. Per-Run & Clear-All Report Deletion** | `DELETE /api/videos/{fn}/reports/{run_id}` & `DELETE /api/videos/{fn}/reports` | Removes run from all alias `*_reports.json` & deletes `*_detections.json` | `MPLBACKEND=Agg python -m unittest tests/test_video_report_deletion.py` |
| **3. Force-Transcode Cancel Preserves Existing `_h264.mp4`** | `force=true` transcode cancelled mid-flight | Staging `.part.mp4` removed; previous `_h264.mp4` remains intact | `MPLBACKEND=Agg python -m unittest tests/test_transcode_atomic_rollback.py` |
| **4. Multi-Resolution Run Overlay Parity (Run 1/2/3)** | Legacy runs on `2688×1520` (Runs 1,3) & `1920×1086` (Run 2) | Backfills `source_resolution` per run `filename`; all 3 align on both videos | `MPLBACKEND=Agg python -m unittest tests/test_video_report_deletion.py` |
| **5. Policy-Governed Timeline Slider Persistence** | Click between original/`_h264` or recordings with `auto-resume` / `keep-paused` / `reset` | Restores stem timestamp on `auto-resume`/`keep-paused`; resets to `0` on `reset` | `MPLBACKEND=Agg python -m unittest tests/test_scrubber_ux_fixes.py` |

