# Step 3: Supervised Re-ID Learning, Negative Feedback, Dynamic Semantic Badges & Unified Enrollment

> **Parent Master Roadmap**: `.TODO/tracking_intelligence_ux_master_roadmap.md` (Step 3 of 4, `Idea 1`, `Finding 5`, `ADR-08`, `ADR-05`)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` & `docs/architecture/CURRENT_ARCHITECTURE.md`
> **Execution Rule**: Strict **1-Milestone-Per-Turn**. Execute Milestone 1 first via `/frontier-architect continue step_3_supervised_reid_badges_and_enrollment`; Milestones 2 and 3 are deferred to subsequent turns.

---

## Pre-Flight Architecture & Modularity Contract

### Hard Budget & Invariant Guards (Verified via `diagnose.py arch-map`)
- **Zero-Regression Budgets** (`tests/test_step3_architecture_budgets.py`, `tests/test_refactor_contract.py`):
  - `dashboard/static/index.html < 180L` (currently `173L` -> add at most 3 `<script>` tags, target `<= 176L`).
  - `dashboard/static/partials/modals/entity_modals.html < 240L` (currently `231L` -> add `<= 5L`, target `<= 236L`).
  - `dashboard/static/partials/modals/camera_modals.html < 240L` (currently `238L` -> **0 lines added**; inject dynamic gallery-category filter bar via JS).
  - `dashboard/static/partials/modals/video_modals.html < 240L` (currently `223L`).
  - `dashboard/static/partials/tabs/gallery.html < 220L` (currently `30L`).
  - `dashboard/static/js/interactive_canvas.js < 240L` (currently `236L` -> delegate new discourage logic to `tag_feedback_actions.js`).
  - `dashboard/static/js/camera_ai_config.js < 280L` (currently `277L` -> delegate gallery-category UI to `category_badge_manager.js`).
  - `dashboard/static/video_scrubber.js < 350L` (currently `389L` WARN -> extract `scrubber_timeline_slider.js` in Milestone 3 to drop `< 340L`).
  - `dashboard/routers/rsac.py` (`347L`), `intelligent_tracker/rsac.py` (`412L`, `14` methods), `dashboard/services/roi_recognition_service.py` (`346L`) -> **do NOT grow**; place new routes/logic in dedicated submodules.
  - `intelligent_tracker/enrollment.py:51` (`enroll()` is `96L`) -> decompose into `<= 40L` helpers before adding collision logic.
- **Database & Concurrency Invariants**:
  - Every write method in `intelligent_tracker/repositories/*_repo.py` MUST call `self._conn.rollback()` inside `except` before re-raising.
  - Offload sync SQLite/gallery calls in `async def` FastAPI routes via `asyncio.to_thread`.
  - Use `HTTPConnection = None  # type: ignore[assignment]` for FastAPI connection injection and handle `DependsParam` in router helpers called directly by unit tests.
  - Never apply full-frame `bbox` coordinates to an already-cropped `crop_base64` payload (`extract_roi_crop(..., is_direct_crop=True)`).
  - Preserve `0` `!important` in CSS and keep standalone fallbacks in parent JS modules so legacy Node VM (`vm.runInNewContext`) tests remain green.

### Public Surface Contracts
- **Negative / Correction Exemplars (Milestone 1)**:
  - Table `negative_exemplars(id INTEGER PK, entity_id INTEGER NULL FK->entities(id) ON DELETE CASCADE, label TEXT DEFAULT '', embedding BLOB NOT NULL, crop_path TEXT DEFAULT '', reason TEXT DEFAULT 'false_positive', camera_id TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)`.
  - `POST /api/tag/discourage`: accepts `{ entity_id?, label?, camera_id?, video_filename?, timestamp_sec?, bbox?, crop_base64?, track_id?, reason? }` -> `{ status: "discouraged", exemplar_id, entity_id, label, crop_path }`.
  - `GET /api/tag/negatives` (optional `?entity_id=<id>`) -> `{ count, negatives: [...] }`.
  - `DELETE /api/tag/negatives/{exemplar_id}` -> `{ status: "deleted", exemplar_id }`.
- **Dynamic Semantic Category Badges & Pre-Enrollment Collision Guard (Milestone 2)**:
  - `PUT /api/rsac/categories/{category_id}`: updates `{ name, color, badge_icon, description }` -> `{ status: "updated", category }`.
  - `POST /api/enroll/check-collision`: accepts `{ camera_id?, video_filename?, timestamp_sec?, bbox?, crop_base64?, threshold?=0.72, top_k?=3 }` -> `{ has_collision: bool, threshold: float, matches: [{ entity_id, name, category, similarity }] }`.
  - `POST /api/enroll`: adds optional `merge_entity_id: Optional[int] = None` and `force_create_new: bool = False` so operators explicitly choose **Merge** (adds signature to `merge_entity_id`) vs. **Create New** when a visual collision is detected.
- **Target Class Filter Split & Extracted Scrubber (Milestone 3)**:
  - `GET /api/system/capabilities`: adds `tracked_categories` (live from `RSACManager`/DB) alongside `coco_classes`, `default_classes`, and `class_presets`.
  - `CameraAddRequest`, `CameraUpdateRequest`, `VideoAnalyzeRequest`, `VideoAddAsCameraRequest`, `PipelineConfig`: add optional `tracked_categories: Optional[List[str]] = None` (default `None` = all gallery categories) kept strictly separate from `classes` (`detector_classes`, COCO).
  - `window.ScrubberTimelineSlider` (`dashboard/static/js/scrubber_timeline_slider.js`): reusable slider/play/prev/next/time controller mounted in both `#tab-videos` (`VideoScrubber`) and `#modal-universal-enrollment` (when a `"Recorded Videos"` source is chosen from `#enroll-camera-select`).

---

## Milestone 1: Negative & Correction Exemplars + Draw-Anywhere Discourage Flow *(Active Slice)*

- [x] **intelligent_tracker/repositories/schema_manager.py**: Add idempotent `CREATE TABLE IF NOT EXISTS negative_exemplars (...)` and index `idx_negative_exemplars_entity` inside `SchemaMixin._init_schema()`.
- [x] **intelligent_tracker/repositories/negative_exemplar_repo.py**: Create `NegativeExemplarMixin` (`<= 160L`, `<= 6` methods: `add_negative_exemplar`, `get_negative_exemplars`, `get_negative_embeddings`, `delete_negative_exemplar`, `clear_negative_exemplars`), calling `self._conn.rollback()` in every write `except` block; compose into `TrackerDB` in `intelligent_tracker/database.py`.
- [x] **intelligent_tracker/matching/gallery.py & intelligent_tracker/matching/_gallery_matching.py**: Load negative exemplar matrix/entity-ids/labels in `GalleryMatcher.reload_gallery()` (keeping `db.get_gallery_embeddings()` strictly positive-only). In `match_persistent_gallery()`, suppress any candidate `entity_id` matching its negative exemplar (`sim >= negative_suppression_threshold`, default `0.78`) and suppress global false-positive/clutter detections (`entity_id is None`, `sim >= global_negative_threshold`, default `0.82`) before confirming identity or calling `_notify_active_learning()`.
- [x] **dashboard/services/negative_exemplar_service.py**: Create `NegativeExemplarService` (`<= 150L`) reusing `RoiRecognitionService.resolve_roi_frame` + `extract_roi_crop(..., is_direct_crop=...)` and `EntityTaggerService._compute_deterministic_embedding` to persist negative exemplars, save bounded crops, record rejection feedback in `ConfidenceEngine` (when `entity_id` is supplied), and clear mismatched live track identity if `track_id` matches.
- [x] **dashboard/routers/tagging.py**: Add thin `POST /api/tag/discourage`, `GET /api/tag/negatives`, and `DELETE /api/tag/negatives/{exemplar_id}` routes (`<= 20L` each), triggering `reload_all_galleries(conn=request)` on writes.
- [x] **dashboard/static/js/tag_feedback_actions.js, dashboard/static/partials/modals/entity_modals.html, dashboard/static/js/interactive_canvas.js & dashboard/static/index.html**: Add a compact `#btn-tag-discourage` ("Not This / False Positive") button inside `#modal-tag-entity` (keeping `entity_modals.html < 240L`), delegate discourage POST (`POST /api/tag/discourage`) and per-candidate discourage click handling to `window.TagFeedbackActions` (keeping `interactive_canvas.js < 240L`), and load `tag_feedback_actions.js` in `index.html`.
- [x] **tests/test_step3_negative_exemplars.py**: Add isolated unit, API (`TestClient` with mocked lifespan/temp DB), and Node VM tests verifying negative-exemplar SQLite persistence & rollback, `GalleryMatcher` per-entity and global false-positive suppression, `POST /api/tag/discourage` + `GET/DELETE /api/tag/negatives`, and `#modal-tag-entity` discourage UX.

---

## Milestone 2: Dynamic Semantic Category Badges CRUD & Pre-Enrollment Collision Guard

- [x] **intelligent_tracker/enrollment.py**: Refactor `UniversalEnrollmentManager.enroll()` (`96L` -> `<= 40L` helpers), add `check_collision(frame=None, bbox=None, crop=None, threshold=0.72, top_k=3)` using `db.get_gallery_embeddings()` + `batch_cosine_similarity`, and support `merge_entity_id` / `force_create_new` in `enroll()`.
- [x] **dashboard/routers/categories_and_collision.py & dashboard/app.py**: Create thin router (`<= 140L`) exposing `PUT /api/rsac/categories/{category_id}` and `POST /api/enroll/check-collision` (offloading sync DB/embedding calls via `asyncio.to_thread`), and mount it in `dashboard/app.py` (keeping `dashboard/routers/rsac.py` frozen at `<= 350L`). Update `dashboard/schemas.py` (`EnrollmentRequest` optional `merge_entity_id`, `force_create_new`; `CollisionCheckRequest`; `CustomCategoryUpdateRequest`).
- [x] **dashboard/static/js/category_badge_manager.js & dashboard/static/index.html**: Create `window.CategoryBadgeManager` (`<= 260L`) to fetch/cache `/api/rsac/categories`, dynamically sync `<select>` options and `.filter-pill` buttons across `#enroll-category-select`, `#tag-category-select`, `#quick-enroll-category-select`, `#modal-zone-category-select`, and `#gallery-category-filters`, render dynamic custom badge colors/icons (`--badge-color`), and power an inline Category Badge CRUD panel inside `#tab-gallery` (`dashboard/static/partials/tabs/gallery.html`).
- [x] **dashboard/static/js/universal_enrollment.js, dashboard/static/partials/modals/entity_modals.html, dashboard/static/js/interactive_canvas.js, dashboard/static/js/review_modals.js, dashboard/static/js/gallery_timeline.js & dashboard/static/css/badges.css**: Wire `CategoryBadgeManager` (with safe fallback for isolated legacy Node VM tests), add pre-enrollment collision check (`POST /api/enroll/check-collision`) in `universal_enrollment.js` surfacing an inline `#enroll-collision-banner` (`Merge into Existing` vs. `Create New`) before `POST /api/enroll`, and add custom-badge CSS variable fallback in `badges.css` (zero `!important`).
- [x] **tests/test_step3_badges_and_collision.py**: Add unit, FastAPI `TestClient`, and Node VM tests verifying `PUT /api/rsac/categories/{id}`, `POST /api/enroll/check-collision` cosine detection, Merge vs. Create New commit paths, and dynamic badge sync across all 5 UI targets.

---

## Milestone 3: Target Class Filter Split (`COCO` vs. `Gallery`), Extracted Enrollment Scrubber & Full Sign-Off

- [x] **dashboard/routers/system.py, dashboard/schemas.py, dashboard/services/camera_config_store.py & dashboard/services/stream_pool_coordinator.py**: Expose `tracked_categories` alongside `coco_classes` in `GET /api/system/capabilities`; add optional `tracked_categories: Optional[List[str]] = None` to camera/video request schemas and camera config persistence (keeping `camera_config_store.py < 180L` and `stream_pool_coordinator.py < 240L`).
- [x] **intelligent_tracker/pipeline/config.py, intelligent_tracker/matching/gallery.py & intelligent_tracker/matching/_gallery_matching.py**: Carry `tracked_categories` into `PipelineConfig` and `GalleryMatcher` so `match_persistent_gallery()` filters matched gallery entities by allowed semantic categories when configured, strictly decoupled from YOLO COCO `detector_classes`.
- [x] **dashboard/static/js/scrubber_timeline_slider.js, dashboard/static/video_scrubber.js & dashboard/static/index.html**: Extract reusable `window.ScrubberTimelineSlider` (`<= 180L`) from `video_scrubber.js` (reducing `video_scrubber.js` from `389L` to `< 340L`, resolving the `> 350L` warning) while preserving all existing `#scrubber-*` DOM IDs and legacy Node VM compatibility.
- [x] **dashboard/static/js/universal_enrollment.js & dashboard/static/partials/modals/entity_modals.html**: Populate `#enroll-camera-select` with `<optgroup label="Camera Profiles">` and `<optgroup label="Recorded Videos">` (`/api/videos`); when a recorded video is selected, mount a `<video>` element + `ScrubberTimelineSlider` instance inside `.modal-left-col` that captures the scrubbed frame onto `#enroll-bbox-canvas` for ROI selection and enrollment.
- [x] **dashboard/static/js/camera_ai_config.js, dashboard/static/js/video_batch.js, dashboard/static/js/video_feed_modal.js & dashboard/static/partials/modals/video_modals.html**: Split filter labels/controls into `Detector Classes (COCO)` and `Tracked Gallery Categories` (dynamically injected for `camera_modals.html` to preserve its `< 240L` ceiling) wired into `POST/PUT /api/cameras`, `POST /api/videos/{filename}/analyze`, and `POST /api/videos/{filename}/add_as_camera`.
- [x] **tests/test_step3_class_split_and_enrollment_scrubber.py**: Add unit, API, and Node VM tests verifying `tracked_categories` filtering vs. COCO `detector_classes`, `ScrubberTimelineSlider` extraction and `video_scrubber.js < 350L`, Enrollment recorded-video scrubbing onto `#enroll-bbox-canvas`, and COCO vs. Gallery UI split.
- [x] **CHANGELOG.md**: Record Step 3 completion via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add` after full Master Verification Gate passes.

---

## Scenario Combinations Matrix

| Scenario | Precondition | Action | Expected Outcome |
| :--- | :--- | :--- | :--- |
| **Per-Entity Negative Exemplar** | Entity `Alice` enrolled; similar-looking person `Bob` falsely matches `Alice` | Operator clicks track or draws ROI -> clicks **Not This / False Positive** (`POST /api/tag/discourage` with `entity_id=Alice`) | Negative exemplar persisted in `negative_exemplars`; `GalleryMatcher` suppresses `Alice` match for `Bob`'s embedding (`sim >= 0.78`) while still matching genuine `Alice` embeddings |
| **Global False-Positive Suppression** | Static coat rack repeatedly triggers `person` detection | Operator draws ROI -> clicks **False Positive** (`entity_id=None`) | Global negative exemplar persisted; `match_persistent_gallery()` suppresses identification & active-learning triage spam for that visual pattern |
| **Dynamic Category Badge CRUD** | Custom badge `contractor` created via `POST /api/rsac/categories` or edited via `PUT` | Open Enrollment, Tag, Quick-Enroll, Scenario Zone modals & Gallery tab | `contractor` appears with custom color/icon in all 5 dropdowns/filter bars immediately without page reload |
| **Pre-Enrollment Collision Guard** | `Alice` already enrolled with embedding `E` | Operator enrolls crop with `sim(crop, E) >= 0.72` | `POST /api/enroll/check-collision` returns `has_collision: true` with `Alice`; Enrollment modal displays **Merge into Alice** vs. **Create New**; choosing Merge appends signature to `Alice` instead of creating duplicate |
| **COCO vs. Gallery Filter Split** | Camera configured with `classes=["person"]` and `tracked_categories=["vip"]` | Frame contains `person` tracks matching `vip` and `staff` entities | YOLO detects all `person` boxes; `GalleryMatcher` identifies `vip` entities and ignores `staff` gallery matches |
| **Enrollment Recorded-Video Scrubber** | Workspace has uploaded MP4 in `/api/videos` | Operator opens Universal Enrollment -> selects video under `Recorded Videos` -> scrubs slider to `t=2.5s` -> draws ROI | `ScrubberTimelineSlider` seeks `<video>`, renders frame onto `#enroll-bbox-canvas`, extracts rectangular `object-fit: contain` crop, and enrolls cleanly |

---

## Verification Commands (OS-Agnostic)

```bash
# Milestone 1 targeted tests + budget/scan gate
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/repositories/negative_exemplar_repo.py intelligent_tracker/repositories/schema_manager.py intelligent_tracker/database.py intelligent_tracker/matching/gallery.py intelligent_tracker/matching/_gallery_matching.py dashboard/services/negative_exemplar_service.py dashboard/routers/tagging.py dashboard/static/js/tag_feedback_actions.js dashboard/static/js/interactive_canvas.js
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests.test_step3_negative_exemplars tests.test_matcher tests.test_step3_e2e_tagging_flow tests.test_step3_tag_modal_integration tests.test_step3_architecture_budgets

# Milestone 2 targeted tests
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests.test_step3_badges_and_collision tests.test_rsac tests.test_enrollment tests.test_m9_api tests.test_step4_p2_frontend_contracts tests.test_step3_architecture_budgets

# Milestone 3 & Final Step 3 Sign-Off Gate
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" scan --path intelligent_tracker dashboard scripts --strict
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker dashboard scripts --typecheck
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run cold_boot_world_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run replay_pipeline_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run video_studio_contract_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run spa_nine_tab_cdp_probe
MPLBACKEND=Agg python -m unittest discover tests
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" arch-map --path .
python -m sphinx -W --keep-going documentation/ documentation/_build/html/
```