# Step 3: SORT + ByteTrack Persistence, Multi-Box Tag Queue & Learned Classes

> **Parent Master Roadmap**: `.TODO/integration_seams_entity_persistence_master_roadmap.md` (`--parent integration_seams_entity_persistence_master_roadmap --milestone 3`)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 07, 13, 17, 18`), `docs/architecture/CURRENT_ARCHITECTURE.md` (`BUG-22`, `BUG-23`)
> **Locked Design Decisions**:
> 1. **`Classes & Badges` UI Placement (UI Reuse Gate)**: Elevate existing `#gallery-category-crud-panel` inside `#tab-gallery` into a unified 3-section `Classes & Badges` sub-view (`#gallery?view=classes-badges`: COCO Detector Classes & per-camera overrides, Learned Exemplar Classes, and Semantic Category Badges delegating to `CategoryBadgeManager`), preserving 9 top-level SPA tabs (`index.html < 180L`) and zero duplicate CRUD panels.
> 2. **Default `detector.classes` for Ownership (`BUG-23`)**: Default `configs/default.yaml` `detector.classes` to `["person", "backpack", "handbag", "suitcase"]` and add a `"Person + Bags"` preset in `DetectorConfigPanel` so `OwnershipAssociationEngine` (`CARRIES`/`OWNED_BY`/unattended bag) works out of the box without enabling all 80 COCO classes.
> 3. **Granularity Guard**: Split Step 3 into 4 vertical-sliced milestones (`M1..M4`), each strictly capped at `<= 6` modified production files (plus focused new submodules) and dedicated test files (`< 350L` each).

---

## Public Surface, Schema & Modularity Contracts

### 1. API Routes, Schema & Telemetry Payload Contracts
| Surface | Contract / Signature | Owner Module |
| :--- | :--- | :--- |
| **Tracker Config** | `tracker: { type: "sort", max_disappeared: 30, min_hits: 3, iou_threshold: 0.3, high_conf_threshold: 0.4, low_conf_threshold: 0.1 }`; `detector.classes: ["person", "backpack", "handbag", "suitcase"]` | `configs/default.yaml`, `intelligent_tracker/pipeline/config.py`, `dashboard/services/camera_cfg_builder.py` |
| **Hysteresis Lock** | `IdentityHysteresisTracker(confirm_k=3, confirm_threshold=0.65, contradict_m=5)` — binds `entity_id` after `K=3` matches `>= 0.65`; unbinds only after `M=5` consecutive contradicting strong matches or manual `force_bind()`/`clear_track()` | `intelligent_tracker/matching/identity_hysteresis.py` |
| **Track Payload** | Live WS (`/ws/{camera_id}`, `/ws/multiview`) and `Track.to_dict()` emit `entity_id`, `entity_name`, `entity_category`, aligned `category`, optional `avatar_url`, and optional `learned_class` (preserving `hasattr(trk, 'entity_id') == False` for unidentified tracks) | `intelligent_tracker/tracker/track.py`, `dashboard/services/stream_telemetry.py` |
| **Multi-Box Hit-Test & Queue** | `RoiDrawTagger.hitTestTracksAtPoint(srcX, srcY, tracks) -> Track[]` (sorted smallest-area / topmost first; `hitTestTrackAtPoint` preserved); `#tag-track-picker-strip` inside `#modal-tag-entity` queues overlapping/Quick-Tag tracks without dropping untagged items on submit | `dashboard/static/js/roi_draw_tagger.js`, `dashboard/static/js/tag_track_queue.js` |
| **SQLite Schema `v4`** | Idempotent `PRAGMA user_version = 4` adding `learned_classes`, `learned_class_exemplars` (DualModel embeddings + crop path), and `camera_class_overrides` (`camera_id`, `coco_label`, `action: suppress\|relabel`, `target_label`) | `intelligent_tracker/repositories/schema_manager.py`, `intelligent_tracker/repositories/learned_class_repo.py` |
| **Learned Classes API** | `GET/POST /api/classes/learned`, `PUT/DELETE /api/classes/learned/{class_id}`, `POST /api/classes/learned/{class_id}/exemplars`, `POST /api/classes/learned/check-collision`, `GET/PUT/DELETE /api/classes/overrides/{camera_id}` | `dashboard/routers/learned_classes.py`, `dashboard/services/learned_class_service.py` |
| **Unified Sub-View DOM** | `#gallery-category-crud-panel` upgraded into `#gallery-classes-badges-view` with sub-tabs `#cb-tab-coco`, `#cb-tab-learned`, `#cb-tab-badges`; accessible via `#btn-manage-categories` and `#gallery?view=classes-badges` | `dashboard/static/js/classes_badges_manager.js`, `dashboard/static/partials/tabs/gallery.html` |

### 2. Modularity Budget Guardrails (Strict Enforcement)
- Global soft ceiling `<= 350L`/file (hard `< 500L`), `<= 12` methods/class, `<= 40L`/function, routes `<= 25L`.
- **Do-Not-Expand Files (Extract Siblings First)**:
  - `dashboard/static/index.html` (`172L`, cap `< 180L` — keep total `<= 178L`)
  - `dashboard/services/camera_config_store.py` (`173L`, cap `< 180L`)
  - `dashboard/services/stream_pool_coordinator.py` (`233L`, cap `< 240L` — extract `camera_cfg_builder.py`)
  - `dashboard/static/js/interactive_canvas.js` (`236L`, cap `< 240L` — delegate to `tag_track_queue.js`)
  - `dashboard/static/partials/modals/entity_modals.html` (`221L`, cap `< 240L` — `<= 10L` strip container)
  - `intelligent_tracker/detectors/onnx_detector.py` (`344L`, cap `< 350L` — `<= 4L` net delta)
  - `dashboard/static/js/scrubber_overlay.js` (`342L`, cap `< 350L`), `dashboard/static/app.js` (`359L` — do NOT add lines)
- **Test File Split Rule**: Keep every new test module strictly `< 350L` by splitting backend and Node VM frontend tests into sibling modules (`test_step3_tracking_hysteresis_backend.py`, `test_step3_tracking_hysteresis_and_multitag.py`, `test_step3_multitag_queue_ui.py`, `test_step3_learned_classes_backend.py`, `test_step3_learned_classes.py`).

### 3. Scenario Combinations Matrix
| Scenario | Input / Trigger | Expected Outcome | Verification |
| :--- | :--- | :--- | :--- |
| **ByteTrack Occlusion Bridge** | Tracked person drops from conf `0.82` to `0.18` for 4 frames then recovers to `0.79` | Same `track_id` preserved via stage-2 low-conf IoU match; unmatched `0.15` noise creates zero new tracks | `test_step3_tracking_hysteresis_backend.py` |
| **Default Ownership Classes** | New camera booted from `configs/default.yaml` with person + backpack near each other | `tracker=sort`, `classes=["person","backpack","handbag","suitcase"]`, `OwnershipAssociationEngine` emits `CARRIES`/`OWNED_BY` | `test_step3_tracking_hysteresis_backend.py` |
| **Identity Hysteresis Lock** | Frames 1–2 match Alice (`0.72`); Frame 3 matches Alice (`0.74`); Frame 4 detector flickers to `chair` or Bob (`0.66`) | Unbound until Frame 3 (`K=3` lock -> `entity_id=Alice`); Frame 4 keeps Alice locked; unbinds only after `M=5` consecutive strong contradictions or manual tag | `test_step3_tracking_hysteresis_and_multitag.py` |
| **Canvas Avatar & Name Pill** | Track payload includes `entity_name="Alice"` and `avatar_url="/api/crops/alice.jpg"` (plus broken-URL error case) | `UnifiedCanvasOverlay` draws circular avatar + `"Alice"` pill; failed image load degrades gracefully to text pill without `naturalWidth === 0` DOM errors | `test_step3_tracking_hysteresis_and_multitag.py` |
| **Overlapping Multi-Box Click** | Two overlapping boxes clicked at shared point `(x, y)` or `#btn-quick-tag` clicked with 3 active tracks | `#modal-tag-entity` displays `#tag-track-picker-strip` with all overlapping/active tracks; submitting track 1 marks it done and advances to track 2 without closing or dropping untagged tracks | `test_step3_multitag_queue_ui.py` |
| **Learned Class Match & Collision** | Operator enrolls ROI exemplar for `"forklift"`; check-collision tests near-duplicate crop (`cos >= 0.82`); camera overrides suppress `"dog"` & relabel `"handbag"` -> `"toolbag"` | `FrameProcessor` suppresses `"dog"`, relabels `"handbag"`, and tags matching crops with `learned_class="forklift"`; collision endpoint flags similar learned class/entity | `test_step3_learned_classes_backend.py`, `test_step3_learned_classes.py` |
| **Schema v4 Idempotency & Rollback** | Existing v3 SQLite DB upgraded twice; forced `sqlite3.Error` inside `learned_class_repo` write | Upgrade succeeds idempotently (`user_version == 4`); failed write calls `self._conn.rollback()` and leaves connection usable | `test_step3_learned_classes_backend.py` |

---

## Milestone 1: SORT + ByteTrack 2-Stage Association, Default Config & Ownership Classes *(Active)*

**Goal**: Make `sort` with ByteTrack two-stage low-confidence association the default tracker across live and batch pipelines, forward per-camera tracker tuning cleanly, and preserve person+bag ownership classes out of the box (`BUG-23`, `ADR-17`).

- [x] **configs/default.yaml**: Switch default `tracker.type` to `sort` (`iou_threshold: 0.3`, `min_hits: 3`, `high_conf_threshold: 0.4`, `low_conf_threshold: 0.1`) and default `detector.classes` to `["person", "backpack", "handbag", "suitcase"]`.
- [x] **intelligent_tracker/tracker/bytetrack_association.py**: Create pure helper module (`<= 150L`, functions `<= 40L`) implementing `split_detections_by_confidence()` and `associate_two_stage()` (stage-1 high-confidence IoU+appearance Hungarian match, stage-2 low-confidence IoU-only recovery for remaining active/coasting tracks, suppressing unmatched low-conf detections from spawning phantom tracks).
- [x] **intelligent_tracker/tracker/sort.py**: Wire `high_conf_threshold` and `low_conf_threshold` into `SortTracker.__init__` and `update()` via `bytetrack_association.associate_two_stage`, keeping existing `coast_frames`/`coast_seconds` and single-stage compatibility intact when `low_conf_threshold <= 0`.
- [x] **intelligent_tracker/detectors/onnx_detector.py**: Support optional `low_conf_threshold` parameter (`<= 4L` net delta, staying strictly `< 350L`) so low-confidence candidates reach ByteTrack stage-2 while preserving existing `conf_threshold` behavior when omitted.
- [x] **intelligent_tracker/pipeline/config.py**: Change default `tracker_type` from `"centroid"` to `"sort"`, parse `high_conf_threshold`/`low_conf_threshold` and `agnostic_nms`, and forward them into `PipelineEngine` / `build_tracker` / `build_detector_with_status` (`intelligent_tracker/pipeline/bundle.py` if needed, `<= 10L`).
- [x] **intelligent_tracker/batch.py**: Change `VideoIndexer` default `tracker_type` from `"centroid"` to `"sort"` and pass optional `tracker_type` through `dashboard/services/video_analytics_service.py` without exceeding `350L`.
- [x] **dashboard/services/camera_cfg_builder.py**: Extract per-camera custom config builder (`<= 80L`) from `dashboard/services/stream_pool_coordinator.py` (keeping coordinator `< 240L`) to forward `detector.{model,confidence,classes,agnostic_nms}`, `tracker.{type,min_hits,iou_threshold,max_disappeared,high_conf_threshold,low_conf_threshold}`, and `reid.tracked_categories`.
- [x] **dashboard/services/camera_config_store.py**: Switch seeded/default camera `tracker` from `"centroid"` to `"sort"` and support optional tracker tuning fields while keeping file strictly `< 180L`.
- [x] **dashboard/static/partials/modals/detector_config_panel.html**: Add `"Person + Bags"` class preset chip alongside existing presets and wire it in `dashboard/static/js/detector_config_panel.js`.
- [x] **tests/test_step3_tracking_hysteresis_backend.py**: Add unit tests verifying ByteTrack 2-stage low-conf occlusion bridging, zero phantom tracks from unmatched low-conf noise, `sort` default across YAML/`PipelineConfig`/`CameraConfigStore`/`VideoIndexer`, per-camera tracker tuning propagation, and `OwnershipAssociationEngine` person+bag `CARRIES`/`OWNED_BY` activation with default classes.
- [x] **Verifier (M1)**:
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/tracker/bytetrack_association.py intelligent_tracker/tracker/sort.py intelligent_tracker/detectors/onnx_detector.py intelligent_tracker/pipeline/config.py intelligent_tracker/batch.py dashboard/services/camera_cfg_builder.py dashboard/services/stream_pool_coordinator.py dashboard/services/camera_config_store.py dashboard/static/js/detector_config_panel.js tests/test_step3_tracking_hysteresis_backend.py --max-lines 350 --max-fn-lines 40`
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step3_tracking_hysteresis_backend.py tests/test_tracker.py tests/test_persistent_coasting.py tests/test_world_ownership.py tests/test_dashboard_di.py`

---

## Milestone 2: Identity Hysteresis Lock (`K=3` / `>= 0.65`) & Entity Name/Avatar Canvas Rendering *(Deferred to Next Turn / Milestone)*

**Goal**: Prevent frame-by-frame Re-ID flickering via `K=3` hysteresis identity locking (`sim >= 0.65`, `M=5` contradiction unbind) and render entity names + circular avatars on canvas boxes across Live, Video Studio, Alerts, and Multiview (`BUG-23`, `ADR-17`).

- [ ] **intelligent_tracker/matching/identity_hysteresis.py**: Create `IdentityHysteresisTracker` (`<= 160L`, `<= 10` methods) managing candidate match streaks (`K=3`, `sim >= 0.65`), locked `(entity_id, entity_name, entity_category, avatar_url)` state surviving detector dropouts/class flips, contradiction counter (`M=5` consecutive strong differing matches to switch/unbind), `force_bind()` / `clear_track()` manual overrides, and `prune_stale()`.
- [ ] **intelligent_tracker/matching/gallery.py**: Instantiate `IdentityHysteresisTracker` on `GalleryMatcher`, wire it through `intelligent_tracker/matching/_gallery_matching.py` and `intelligent_tracker/matching/_gallery_signals.py`, decorate confirmed tracks with resolved `avatar_url` and `entity_category`, and reinforce `WorldEntity` bindings rather than replacing on single-frame noise.
- [ ] **intelligent_tracker/tracker/track.py**: Expose optional `avatar_url` and `learned_class` in `Track.to_dict()` (using `getattr(..., None)` so unidentified tracks preserve `hasattr(trk, 'entity_id') == False`), and sync `dashboard/services/stream_telemetry.py` (`_extract_track_telemetry`) to emit `avatar_url`, `learned_class`, and aligned `category` (`entity_category` fallback).
- [ ] **dashboard/services/entity_tagger.py**: Call hysteresis `force_bind()` (when matcher present) during `_update_live_track_identity()` and `dashboard/services/roi_recognition_service.py` commits so manual operator tags override hysteresis immediately.
- [ ] **dashboard/static/js/overlay_avatar_cache.js**: Create bounded LRU avatar `Image` loader (`<= 110L`) with `onerror` graceful degradation (never leaving broken DOM `<img>` nodes), load it in `dashboard/static/index.html` (keeping `< 180L`), and render circular avatar badges + entity name pills in `dashboard/static/js/unified_canvas_overlay.js` (`drawLabelPill` / `drawTrackBox`).
- [ ] **tests/test_step3_tracking_hysteresis_and_multitag.py**: Add backend hysteresis state-machine tests (`K=3` lock, class-flip preservation, `M=5` contradiction unbind, manual `force_bind`, WS/to_dict `avatar_url` parity) and Node VM tests for `overlay_avatar_cache.js` + `UnifiedCanvasOverlay` avatar/name rendering.
- [ ] **Verifier (M2)**:
  - `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/matching/identity_hysteresis.py intelligent_tracker/matching/gallery.py intelligent_tracker/matching/_gallery_matching.py intelligent_tracker/matching/_gallery_signals.py intelligent_tracker/tracker/track.py dashboard/services/stream_telemetry.py dashboard/static/js/overlay_avatar_cache.js dashboard/static/js/unified_canvas_overlay.js tests/test_step3_tracking_hysteresis_and_multitag.py --max-lines 350 --max-fn-lines 40`
  - `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step3_tracking_hysteresis_and_multitag.py tests/test_matcher.py tests/test_gallery_signals.py tests/test_step2_unified_canvas_engine.py tests/test_step1_seams_backend.py`

---

## Milestone 3: Multi-Box Overlap Hit-Test & Quick-Tag Queue inside `#modal-tag-entity` *(Deferred to Next Turn / Milestone)*

**Goal**: Return all overlapping boxes on canvas click and queue overlapping or Quick-Tag tracks inside `#modal-tag-entity` via a reusable track picker strip without losing untagged tracks on submit (`BUG-22`, `ADR-18`).

- [ ] **dashboard/static/js/roi_draw_tagger.js**: Add `hitTestTracksAtPoint(srcX, srcY, tracks)` returning all containing tracks sorted deterministically (smallest area / topmost first), keep `hitTestTrackAtPoint()` delegating to the first result for compatibility, and include `overlappingTracks` in `onTrackClick` payloads.
- [ ] **dashboard/static/js/tag_track_queue.js**: Create `TagTrackQueue` controller (`<= 220L`) managing `#tag-track-picker-strip` inside `#modal-tag-entity` (queue initialization from overlapping click hits or Quick-Tag track list, active track chip selection with seq-guarded `runRoiRecognition`, marking committed tracks as done, auto-advancing to the next untagged track on submit instead of closing modal prematurely, and explicit clear on cancel/close).
- [ ] **dashboard/static/css/tag_queue.css**: Create focused stylesheet (`<= 95L`, zero `!important`, `min-width: 0`, `flex-wrap: wrap`, `>= 8px` gaps) for `#tag-track-picker-strip` chips and progress indicator.
- [ ] **dashboard/static/partials/modals/entity_modals.html**: Insert compact `#tag-track-picker-strip` container inside `#modal-tag-entity` (`<= 8L`, keeping file strictly `< 240L`) and include `tag_track_queue.js` / `tag_queue.css` in `dashboard/static/index.html` (`< 180L`).
- [ ] **dashboard/static/js/interactive_canvas.js**: Wire `TagTrackQueue` into `openTagModal`, `#btn-quick-tag` (passing all active tracks rather than `tracks[0]` only), and `submitTagForm` (advancing queue when untagged items remain) while keeping `interactive_canvas.js < 240L`; also update `dashboard/static/js/scrubber_overlay.js` (or small helper) so `getTracksAtCurrentTime()` collects overlapping tracks across all visible active run layers.
- [ ] **tests/test_step3_multitag_queue_ui.py**: Add Node VM tests covering `hitTestTracksAtPoint` multi-hit ordering, `#tag-track-picker-strip` switching, Quick-Tag batch submit retaining untagged tracks until queue completion, and regression parity with `tests/test_step3_roi_draw_tagger.py` and `tests/test_step3_tag_modal_integration.py`.
- [ ] **Verifier (M3)**:
  - `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/static/js/roi_draw_tagger.js dashboard/static/js/tag_track_queue.js dashboard/static/js/interactive_canvas.js dashboard/static/partials/modals/entity_modals.html dashboard/static/index.html tests/test_step3_multitag_queue_ui.py --max-lines 350 --max-fn-lines 40`
  - `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step3_multitag_queue_ui.py tests/test_step3_roi_draw_tagger.py tests/test_step3_tag_modal_integration.py tests/test_step2_video_scrubber_parity.py`

---

## Milestone 4: Exemplar Learned Classes, Per-Camera COCO Overrides, `Classes & Badges` Sub-View & Sign-Off *(Deferred to Next Turn / Milestone)*

**Goal**: Implement exemplar-based Learned Classes (DualModel ROI crop prototypes + cosine collision checks), per-camera COCO suppression/relabel overrides wired live into `FrameProcessor`, and the unified `Classes & Badges` sub-view inside `#tab-gallery`, followed by full Step 3 verification and Review Gate sign-off (`ADR-18`).

- [ ] **intelligent_tracker/repositories/schema_manager.py**: Add idempotent `PRAGMA user_version = 4` migration creating `learned_classes`, `learned_class_exemplars`, and `camera_class_overrides` tables with indexes.
- [ ] **intelligent_tracker/repositories/learned_class_repo.py**: Create `LearnedClassMixin` (`<= 220L`, `<= 12` methods, every write calling `self._conn.rollback()` in `except`) and compose it into `TrackerDB` (`intelligent_tracker/database.py`).
- [ ] **intelligent_tracker/matching/learned_class_matcher.py**: Create `LearnedClassMatcher` (`<= 190L`) loading DualModel exemplar prototypes from `TrackerDB`, scoring ROI crop embeddings via cosine similarity, enforcing per-camera COCO suppression/relabel rules, and providing `check_collision()` against existing learned classes and gallery entities; wire into `intelligent_tracker/pipeline/bundle.py` and `intelligent_tracker/pipeline/frame_processor.py` (`_run_detector()`).
- [ ] **dashboard/services/learned_class_service.py**: Create service (`<= 210L`) handling learned class CRUD, ROI crop extraction/embedding enrollment via canonical `DualModel` (`ReidProfile` SSOT), collision check responses, per-camera COCO override persistence, and live matcher reload across `CameraPool`.
- [ ] **dashboard/routers/learned_classes.py**: Create thin FastAPI router (`<= 160L`, routes `<= 25L`) exposing `/api/classes/learned*` and `/api/classes/overrides/{camera_id}`, mounted in `dashboard/app.py`.
- [ ] **dashboard/static/js/classes_badges_manager.js**: Create unified `Classes & Badges` sub-view controller (`<= 290L`) plus `dashboard/static/css/classes_badges.css` (`<= 120L`), elevating `#gallery-category-crud-panel` in `dashboard/static/partials/tabs/gallery.html` (`#gallery?view=classes-badges`) into 3 tabs: COCO Detector Classes + per-camera suppress/relabel rules, Learned Exemplar Classes (with collision guard), and Semantic Category Badges (delegating CRUD directly to `dashboard/static/js/category_badge_manager.js`).
- [ ] **tests/test_step3_learned_classes_backend.py**: Add backend tests covering schema v4 idempotency, repository rollback on error, `LearnedClassMatcher` prototype matching & collision detection, per-camera COCO suppress/relabel in `FrameProcessor`, and `/api/classes/*` FastAPI router CRUD.
- [ ] **tests/test_step3_learned_classes.py**: Add Node VM tests for `ClassesBadgesManager` (3-section view switching, COCO override save, learned class enrollment + collision prompt, badge delegation to `CategoryBadgeManager`) and `#gallery?view=classes-badges` deep-link activation.
- [ ] **CHANGELOG.md**: Record Step 3 completion via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add`.
- [ ] **Verifier (M4 & Step 3 Sign-Off)**:
  - `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/repositories/learned_class_repo.py intelligent_tracker/matching/learned_class_matcher.py dashboard/services/learned_class_service.py dashboard/routers/learned_classes.py dashboard/static/js/classes_badges_manager.js tests/test_step3_learned_classes_backend.py tests/test_step3_learned_classes.py --max-lines 350 --max-fn-lines 40`
  - `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict`
  - `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" scan --path .`
  - `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step3_tracking_hysteresis_backend.py tests/test_step3_tracking_hysteresis_and_multitag.py tests/test_step3_multitag_queue_ui.py tests/test_step3_learned_classes_backend.py tests/test_step3_learned_classes.py`
  - `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run replay_pipeline_probe`
  - `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run spa_nine_tab_cdp_probe`
  - `MPLBACKEND=Agg python -m unittest discover tests`
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`
  - **Review Gate**: Fresh reviewer inspects Step 3 diff, modularity audit, tracker stability metrics, multi-box queue persistence, and non-`INFRA_UNAVAILABLE` probe outputs before advancing Master Roadmap Milestone 3.
