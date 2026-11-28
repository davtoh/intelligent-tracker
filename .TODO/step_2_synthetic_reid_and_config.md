# Step 2: Synthetic Re-ID Parity, Live ROI-Draw Enrollment & Camera/Batch Config

> **Parent Master Roadmap**: `.TODO/runtime_ux_and_reid_parity_master_roadmap.md` (`--parent runtime_ux_and_reid_parity_master_roadmap --milestone 2`)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 10, 11, 13, 21`), `docs/architecture/CURRENT_ARCHITECTURE.md` (`OBS-004`, `OBS-005`, `OBS-006`, `OBS-007`, `OBS-010`, `OBS-018`)
> **Goal**: Align `MockDetector` (`intelligent_tracker/detectors/mock_detector.py`) with `SyntheticFrameGenerator` `P1`/`P2` pixel regions so enrolled `P1` matches in `#live` (`synthetic_01`) and `#videos` batch runs (`OBS-005`, `OBS-006`, `OBS-007`), refresh `#gallery` cleanly after enrollment even with active category/search filters (`OBS-004`), trigger debounced `/api/enroll/check-collision` + `/api/tag/recognize-roi` object suggestions on ROI `mouseup` (`OBS-010`), preserve `tracked_categories` & `agnostic_nms` across `GET /api/cameras` -> Edit (`OBS-018`), preserve `tracked_categories` in `video_analytics_service.py` `config_meta`, and expose `#gallery`/learned-class pickers + clear COCO vs. RSAC helper copy in Batch & Camera modals (`OBS-006`, `OBS-018`).

---

## Public Surface, Modularity Budgets & Contracts

### 1. Modularity Budget Guardrails (Strict Enforcement)
- Global soft ceiling `<= 350L`/file (hard `< 500L`), `<= 12` methods/class, `<= 40L`/function, routes `<= 25L`.
- **Critical Tight-Cap Files**:
  - `dashboard/static/js/camera_ai_config.js`: **HARD CAP `< 280L`** (`tests/test_step3_class_split_and_enrollment_scrubber.py`).
  - `dashboard/static/js/universal_enrollment.js`: `<= 349L`.
  - `dashboard/services/video_analytics_service.py`: `<= 350L`.
  - `dashboard/static/js/gallery_timeline.js`: `<= 350L`.
  - `dashboard/routers/system.py`, `dashboard/routers/cameras.py`, `dashboard/schemas.py`: `<= 350L`.

### 2. Scenario Combinations Matrix
| Scenario | Input / Trigger | Expected Outcome | Verification |
| :--- | :--- | :--- | :--- |
| **Synthetic `P1` Enroll -> `#live` & `#videos`** | Enroll `P1` on `synthetic_01`, run `MockDetector` + `GalleryMatcher` on synthetic frames | `MockDetector` locks onto `P1`/`P2` pixel regions; `GalleryMatcher` matches `P1` | `test_step2_synthetic_reid_and_config.py`, `replay_pipeline_probe` |
| **Enrollment `#gallery` Filter Refresh** | Active search or category filter in `#gallery`; enroll new entity | `loadGallery({ highlightEntityId })` clears mismatched filters so new entity renders immediately | `test_step2_synthetic_reid_and_config.py` |
| **Live ROI-Draw Collision & AI Suggestion** | Drag ROI on `#enroll-bbox-canvas` (`mouseup`) | Debounced `check-collision` + `recognize-roi` update `#enroll-crop-meta` and `#enroll-collision-banner` | `test_step2_synthetic_reid_and_config.py` |
| **Camera Add -> `GET /api/cameras` -> Edit** | Create camera with `tracked_categories` and `agnostic_nms`, click Edit & Save | `GET /api/cameras` exposes `tracked_categories` and `agnostic_nms`; `buildCameraPayload` retains them | `test_step2_synthetic_reid_and_config.py` |
| **Batch & Camera Gallery Pickers** | Open `#modal-video-batch-analyze` or camera AI config panel | Enrolled `#gallery` entity pills, RSAC category chips, and COCO vs. RSAC helper copy render cleanly | `test_step2_synthetic_reid_and_config.py`, `video_studio_contract_probe` |

---

## Milestone 1: Synthetic Re-ID Parity, Live ROI-Draw Enrollment & Camera/Batch Config *(Active)*

- [x] **intelligent_tracker/detectors/mock_detector.py**: Detect `SyntheticFrameGenerator` `P1`/`P2` pixel regions via `_extract_color_box()` / `_detect_synthetic_targets()` while keeping `preset_boxes` and blank-frame fallback intact (`OBS-005`, `OBS-006`, `OBS-007`).
- [x] **dashboard/schemas.py**: Add `agnostic_nms` to `CameraAddRequest` and `CameraUpdateRequest` (`OBS-018`).
- [x] **dashboard/routers/cameras.py**: Forward `req.agnostic_nms` in `add_camera()` and `update_camera()` (`OBS-018`).
- [x] **dashboard/camera_pool.py**: Accept and forward `agnostic_nms` in `add_camera()` and `update_camera()` (`OBS-018`).
- [x] **dashboard/services/camera_pool_queries.py**: Include `tracked_categories` and `agnostic_nms` in `build_camera_status_row()`, and add mixin type annotations so `mypy` passes cleanly (`OBS-018`).
- [x] **dashboard/services/video_analytics_service.py**: Preserve `tracked_categories` in `config_meta` for `submit_async_analytics_job()` and `run_sync_analytics()` while staying `<= 350L` (`OBS-006`).
- [x] **dashboard/routers/system.py**: Expose `enrolled_entities` in `GET /api/system/capabilities` (`OBS-006`, `OBS-018`).
- [x] **dashboard/static/js/gallery_timeline.js**: Add `resetGalleryFilters()` and auto-reset filters in `loadGallery({ highlightEntityId })` when the new entity would be hidden (`OBS-004`).
- [x] **dashboard/static/js/enrollment_stage_controller.js**: Add debounced `scheduleRoiPreviewCheck()` and `cancelRoiPreviewCheck()` calling `/api/enroll/check-collision` and `/api/tag/recognize-roi` (`OBS-010`).
- [x] **dashboard/static/js/universal_enrollment.js**: Trigger `scheduleRoiPreviewCheck()` on ROI crop extraction, `cancelRoiPreviewCheck()` on reset, and `highlightEntityId` on `loadGallery()` while staying `<= 349L` (`OBS-004`, `OBS-010`).
- [x] **dashboard/static/js/camera_form_helpers.js**: Preserve `agnostic_nms` in `buildCameraPayload()`, add `renderGalleryEntitiesHint()`, and render COCO vs. RSAC helper text + gallery entity pills in `syncTrackedCategoriesUI()` (`OBS-018`).
- [x] **dashboard/static/js/camera_ai_config.js**: Re-sync `CategoryChipPicker.mountForInput('cam-tracked-categories-input')` inside `setValues()` while staying `< 280L` (`OBS-018`).
- [x] **dashboard/static/partials/modals/detector_config_panel.html**: Clarify COCO detector classes vs. gallery Re-ID matching (`OBS-018`).
- [x] **dashboard/static/partials/modals/video_modals.html**: Add COCO vs. RSAC helper copy and `#batch-gallery-entities-hint` container (`OBS-006`).
- [x] **dashboard/static/js/video_batch.js**: Hydrate `#batch-gallery-entities-hint` and sync `CategoryChipPicker` on `openBatchModal()` (`OBS-006`).
- [x] **tests/test_step2_synthetic_reid_and_config.py**: Add isolated unit + Node VM tests (`<= 350L`, methods `<= 40L`) verifying `MockDetector` synthetic `P1`/`P2` detection + `DualModel` E2E Re-ID match, camera config round-trip, `video_analytics_service` `config_meta`, capabilities `enrolled_entities`, `#gallery` filter auto-reset, live ROI-draw collision/recognition preview, and camera/batch modal pickers.
- [x] **Verifier (Step 2)**:
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/detectors/mock_detector.py dashboard/schemas.py dashboard/routers/cameras.py dashboard/camera_pool.py dashboard/services/camera_pool_queries.py dashboard/services/video_analytics_service.py dashboard/routers/system.py dashboard/static/js/universal_enrollment.js dashboard/static/js/enrollment_stage_controller.js dashboard/static/js/gallery_timeline.js dashboard/static/js/video_batch.js dashboard/static/partials/modals/video_modals.html dashboard/static/js/camera_ai_config.js dashboard/static/js/camera_form_helpers.js dashboard/static/partials/modals/detector_config_panel.html tests/test_step2_synthetic_reid_and_config.py --max-lines 350 --max-fn-lines 40`
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step2_synthetic_reid_and_config.py tests/test_detectors.py tests/test_camera_detector_config.py tests/test_pipeline_parity.py tests/test_ci_parity_and_batch_contract.py tests/test_step3_badges_and_collision.py tests/test_step3_class_split_and_enrollment_scrubber.py tests/test_step1_demo_mode_ui.py tests/test_step4_m3_spa_and_video_contracts.py tests/test_step4_p2_frontend_contracts.py`
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run replay_pipeline_probe`
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run video_studio_contract_probe`
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify`
