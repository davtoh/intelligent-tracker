# Step 3 Implementation Plan: Interactive Click-to-Tag & Freehand Draw-to-Tag with On-Demand AI Recognition

> **Parent Master Plan**: `.TODO/live_video_studio_master_roadmap.md` (Step 3)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Subsequent Turns*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map` & `diagnose.py audit`)

Measured against workspace baseline before edits:
- `dashboard/routers/rsac.py`: 345 lines (`OK < 350L`, 5 lines from warning ceiling — frozen against new routes; Step 3 routes go in `dashboard/routers/tagging.py`).
- `dashboard/routers/analytics.py`: 262 lines (`OK < 350L`, contains legacy `POST /tag` and `GET /crops/{filename}`).
- `dashboard/services/entity_tagger.py`: 159 lines (`OK < 350L`, 6 methods `<= 34L`).
- `dashboard/static/js/interactive_canvas.js`: 200 lines (`OK < 350L`, supports `#live` hover/click-to-tag only; lacks drag-to-draw freehand ROI and AI recognition preview).
- `dashboard/static/js/unified_canvas_overlay.js`: 225 lines (`OK < 280L`, provides `computeContainBox`, `syncCanvasDpr`, `resolveScaleFactors`, `renderScene`).
- `dashboard/static/js/scrubber_overlay.js`: 326 lines (`OK < 350L`, renders `#videos` overlay canvas without interactive click-to-tag or drag-to-draw ROI tagging).
- `dashboard/static/partials/modals/entity_modals.html`: 223 lines (`#modal-tag-entity` lacks crop thumbnail preview, AI-predicted class badge, and top-K Re-ID candidate confirmation chips).

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- Existing tagging, enrollment, entity, and crop endpoints (`POST /tag`, `POST /api/enroll`, `GET /entities`, `GET /crops/{filename}`) remain 100% intact and backward-compatible.
- Existing client globals (`window.InteractiveCanvas`, `window.UnifiedCanvasOverlay`, `window.ScrubberOverlay`) retain their exported public signatures.
- Critical DOM IDs remain intact: `#modal-tag-entity`, `#tag-entity-form`, `#tag-track-id`, `#tag-bbox-val`, `#tag-name-input`, `#tag-category-select`, `#tag-notes-input`, `#interactive-canvas`, and `#scrubber-overlay-canvas`.
- `dashboard/routers/` never instantiates `TrackerDB(...)` directly and resolves dependencies through `dashboard.dependencies` (`get_db`, `get_active_stream_manager`, `get_camera_pool`, `get_enrollment_mgr`, `reload_all_galleries`); `intelligent_tracker/` never imports from `dashboard/` or `scripts/`.

### Modularity Guardrails
- `dashboard/services/roi_recognition_service.py` MUST remain `< 240` lines with all methods/functions `<= 35` lines (hard audit ceiling `<= 40` lines).
- `dashboard/routers/tagging.py` MUST remain `< 180` lines with every route handler `<= 25` lines.
- `dashboard/static/js/roi_draw_tagger.js` MUST remain `< 260` lines with every function `<= 35` lines.
- All modified files (`dashboard/app.py`, `dashboard/static/js/interactive_canvas.js`, `dashboard/static/js/scrubber_overlay.js`, `dashboard/static/partials/modals/entity_modals.html`) MUST remain `< 350` lines with all functions `<= 40` lines and zero `!important` CSS declarations.

---

## 3. Phased Implementation Milestones

### Milestone 1: On-Demand ROI Recognition & Tag Commit Backend (`roi_recognition_service.py` & `tagging.py`) *(Active Execution Target)*
- [x] **dashboard/services/roi_recognition_service.py**: Create `RoiRecognitionService` (`< 240L`, methods `<= 35L`) with `resolve_roi_frame` (supporting `camera_id` live frame, `video_filename` + `timestamp_sec` frame seek via `cv2.VideoCapture`, and `crop_base64` decode), `extract_roi_crop`, `classify_roi_crop` (running active detector or aspect/color heuristic fallback), `match_crop_to_gallery` (computing deterministic 128-D embedding and top-K cosine similarity matches via `TrackerDB.get_gallery_embeddings` and `batch_cosine_similarity`), `recognize_roi`, and `commit_roi_tag` (enrolling/updating entity, saving crop to `data/crops/`, recording signature and sighting).
- [x] **dashboard/routers/tagging.py**: Create `APIRouter` (`< 180L`, route handlers `<= 25L`) exposing `POST /api/tag/recognize-roi` and `POST /api/tag/commit` with Pydantic schemas `RoiRecognizeRequest` and `TagCommitRequest`, delegating to `RoiRecognitionService` and `reload_all_galleries`.
- [x] **dashboard/app.py**: Mount `tagging_router` from `dashboard.routers.tagging` and export it in `dashboard/routers/__init__.py` while keeping `app.py` `< 305L`.
- [x] **tests/test_step3_roi_recognition_api.py**: Add isolated unit tests (using `tempfile.TemporaryDirectory()` for `TrackerDB`, videos, and crops) covering `POST /api/tag/recognize-roi` (live `camera_id`, recorded `video_filename` + `timestamp_sec`, `crop_base64`, and empty gallery/fallback branches), `POST /api/tag/commit` (new entity creation, existing entity signature append, gallery reload), and `diagnose.py audit` compliance.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 1 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step3_roi_recognition_api.py"
```

---

### Milestone 2: Unified Click-to-Tag & Freehand Drag-to-Draw Canvas Controller (`roi_draw_tagger.js`) *(Deferred to Next Turn)*
- [x] **dashboard/static/js/roi_draw_tagger.js**: Create `window.RoiDrawTagger` (`< 260L`, functions `<= 35L`) supporting pointer drag-to-draw freehand ROI box selection (`>= 6px` drag) and track click selection (`< 6px` click) on both `#interactive-canvas` (`#live`) and `#scrubber-overlay-canvas` (`#videos`), mapping client coordinates through `UnifiedCanvasOverlay.computeContainBox` to intrinsic media `[x, y, w, h]` coordinates and rendering a live dashed selection overlay.
- [x] **dashboard/static/index.html**: Register `<script src="/static/js/roi_draw_tagger.js"></script>` after `unified_canvas_overlay.js` so both `#live` and `#videos` canvases share `RoiDrawTagger`.
- [x] **tests/test_step3_roi_draw_tagger.py**: Add unit tests verifying `mapClientToSourcePoint`, `normalizeDragRect`, `hitTestTrackAtPoint`, click-vs-drag threshold branching, video pause-on-drag behavior, and `diagnose.py audit` compliance.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 2 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step3_roi_draw_tagger.py"
```

---

### Milestone 3: Tag Modal Live Crop Preview, AI Class Badge & 1-Click Re-ID Candidate Confirmation *(Deferred to Next Turn)*
- [x] **dashboard/static/partials/modals/entity_modals.html**: Upgrade `#modal-tag-entity` with `#tag-roi-preview-panel` (`#tag-roi-crop-img`, `#tag-ai-class-badge`, `#tag-identity-candidates`) and hidden context inputs (`#tag-source-type`, `#tag-video-filename`, `#tag-timestamp-sec`, `#tag-crop-base64`).
- [x] **dashboard/static/js/interactive_canvas.js**: Wire `InteractiveCanvas` and `#tag-entity-form` to `RoiDrawTagger.openWithRecognition()` and `POST /api/tag/commit`, triggering immediate gallery/entity list refresh on commit while keeping `interactive_canvas.js` `< 240L`.
- [x] **dashboard/static/js/scrubber_overlay.js**: Bind `RoiDrawTagger` to `#scrubber-overlay-canvas` in `ScrubberOverlay.init()` so clicking a video track or drag-drawing an ROI on a paused frame opens the AI recognition tag modal, keeping `scrubber_overlay.js` `< 345L`.
- [x] **tests/test_step3_tag_modal_integration.py**: Add unit tests verifying modal preview rendering, AI category auto-selection, 1-click candidate chip selection, `POST /api/tag/commit` submission for both `#live` and `#videos`, and `diagnose.py audit` compliance.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 3 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step3_tag_modal_integration.py"
```

---

### Milestone 4: End-to-End ROI Tagging Verification, Static Audit & Step 3 Sign-Off *(Deferred to Next Turn)*
- [x] **tests/test_step3_e2e_tagging_flow.py**: Add end-to-end integration tests verifying live camera ROI draw -> recognize -> commit -> gallery similarity match and recorded video timestamp ROI draw -> recognize -> commit -> gallery reload, plus non-mocked fallback branch coverage.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 4 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step3_*.py"
```

---

## 4. Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Verify Milestone 1 (ROI Recognition & Tag Commit Backend)** | Headless unit suite | `test_step3_roi_recognition_api.py` | `python -m unittest discover -s tests -p "test_step3_roi_recognition_api.py"` |
| **Verify Milestone 2 (Unified `RoiDrawTagger` Canvas Controller)** | Headless unit suite | `test_step3_roi_draw_tagger.py` | `python -m unittest discover -s tests -p "test_step3_roi_draw_tagger.py"` |
| **Verify Milestone 3 (Tag Modal Preview, AI Badge & `#live`/`#videos` Wiring)** | Headless unit suite | `test_step3_tag_modal_integration.py` | `python -m unittest discover -s tests -p "test_step3_tag_modal_integration.py"` |
| **Verify Milestone 4 (Full Step 3 E2E Tagging Suite)** | Headless unit suite | `test_step3_*.py` | `python -m unittest discover -s tests -p "test_step3_*.py"` |
| **Static Modularity & Function Budget Audit on All Step 3 Files** | AST Auditor | `--max-lines 350 --max-fn-lines 40` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/services/roi_recognition_service.py dashboard/routers/tagging.py dashboard/app.py dashboard/static/js/roi_draw_tagger.js dashboard/static/js/interactive_canvas.js dashboard/static/js/scrubber_overlay.js --max-lines 350 --max-fn-lines 40` |
| **Live Browser Layout & Zero-Overflow Check (`#modal-tag-entity` & Canvases)** | CDP UI Inspector | `--audit-layout` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" ui --url $APP_URL --headless --audit-layout --selectors "#interactive-canvas,#scrubber-overlay-canvas,#modal-tag-entity,#tag-roi-preview-panel"` |
