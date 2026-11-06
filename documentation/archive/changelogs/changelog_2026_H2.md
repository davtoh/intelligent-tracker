<!-- AI AGENT NOTICE: Historical archive only. DO NOT read this file unless explicitly asked to research past migrations. -->

# Historical Changelog Archive (2026 H2)

## [Milestone 9] - 2026-10-26 - Artifact & Face Intelligence, Active Learning & Adaptive Memory

### 1. Objectives & Scope
- Deliver **Universal Artifact & Face Enrollment**: Freeze-frame video cropping, interactive canvas bounding box selection, custom category tagging (`person`, `family_car`, `delivery_truck`, `cleaning_crew`, `guard_dog`, `pet`, `vip`, `restricted`), security clearance roles, and dual-model feature extraction.
- Implement **Role-Based Spatial Access Control (RSAC)**: Category whitelists and denials per zone, time-of-day / day-of-week active schedules, entity-level allow/deny overrides, and domestic pet perimeter intrusion alarm suppression.
- Build **Human-in-the-Loop Active Learning ("Review & Learn" Inbox)**: Automatically queue ambiguous detections ($0.45 \le \text{similarity} < 0.70$) into a dedicated triage pane with 1-click operator actions: **Confirm (Ground Truth)**, **Reassign**, **Enroll as New Entity**, or **Dismiss**.
- Implement **Locked Anchor Descriptors & Continuous Adaptive Memory**: Flag confirmed crops as immutable Locked Anchors, enable bounded Exponential Moving Average (EMA) continuous feature updating, occlusion reasoning (freezing Re-ID identity updates when tracks overlap with $\text{IoU} > 0.3$), and versioned descriptor snapshots with 1-click rollback.
- Integrate full **REST API Surface & Glassmorphism Dashboard UI** (`dashboard/app.py`, `dashboard/static/review_and_rsac.js`, `dashboard/static/index.html`, `dashboard/static/styles.css`).
- Build comprehensive unit test suite in `tests/test_rsac.py`, `tests/test_active_learning.py`, `tests/test_enrollment.py`, `tests/test_occlusion_and_ema.py`, `tests/test_m9_api.py` (22 new tests, 209 total passing).
- Update Sphinx documentation with zero warnings.

### 2. Files Touched & Created
- **Detection, Re-ID & Enrollment:**
  - `intelligent_tracker/detectors.py` *(Modified)*: Added `YuNetFaceDetector(BaseDetector)` utilizing OpenCV Zoo's ONNX face detection model (`models/face_detection_yunet_2023mar.onnx`). Registered with `DetectorFactory`.
  - `intelligent_tracker/reid.py` *(Modified)*: Added `DualModelFeatureExtractor(BaseFeatureExtractor)` combining deep body/artifact appearance embeddings with localized facial biometric vectors into a single L2-normalized vector. Supported `bins` argument in `ColorHistogramExtractor`. Registered with `ReIDExtractorFactory`. Made `bbox` parameter optional in `BaseFeatureExtractor.extract`.
  - `intelligent_tracker/enrollment.py` *(New)*: `UniversalEnrollmentManager` supporting freeze-frame crops, bboxes, base64 payloads, dual-model extraction, locked anchor marking, v1 descriptor snapshot creation, and gallery reload.
  - `scripts/download_models.py` *(Modified)*: Added automated downloading and SHA-256 verification for `face_detection_yunet_2023mar.onnx` (`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`).
- **Spatial Security & Active Learning:**
  - `intelligent_tracker/rsac.py` *(New)*: `CustomCategory`, `RSACSchedule`, `RSACZoneRule`, `RSACDecision`, and `RSACManager` with schedule evaluation, category whitelists/denials, entity overrides, and pet alarm suppression.
  - `intelligent_tracker/active_learning.py` *(New)*: `ActiveLearningManager` with candidate triage ($0.45 \le \text{sim} < 0.70$), debouncing, thumbnail cropping, event dispatching, and operator actions (`confirm_candidate`, `reassign_candidate`, `enroll_as_new`, `dismiss_candidate`), plus `maybe_queue_candidate` helper.
  - `intelligent_tracker/events.py` *(Modified)*: Added `RSACViolationEvent`, `PetActivityEvent`, and `ReviewItemQueuedEvent`. Supported `capacity` kwarg in `EventBus.__init__`.
  - `intelligent_tracker/tracker.py` *(Modified)*: Added track occlusion reasoning (`check_track_occlusions`), cluttered track state tracking (`is_cluttered`, `clutter_partner_id`), supported `centroid` kwarg in `Track.__init__`, and relaxed hits condition to active tracks with `hits >= 1`.
  - `intelligent_tracker/matcher.py` *(Modified)*: Track occlusion Re-ID freezing during clutter, bounded EMA continuous updates, locked anchor drift protection against observation and smoothed vectors, and `max_drift_threshold` parameter support.
  - `intelligent_tracker/analytics.py` *(Modified)*: Pet whitelist intrusion suppression emitting informational `PetActivityEvent`, and RSAC violation alarms emitting `RSACViolationEvent`.
  - `intelligent_tracker/database.py` *(Modified)*: Added tables `descriptor_versions`, `review_queue`, `custom_categories`, `rsac_zone_rules`, `pet_whitelist`. Extended `entity_signatures` with `is_anchor` and `locked`. Added alias methods `add_entity_signature`, `update_entity_signature`, `get_entity_signatures`, and flexible `record_descriptor_version`, `get_descriptor_versions`, and `rollback_descriptor`. Added `PRAGMA wal_checkpoint(TRUNCATE)` in `TrackerDB.close()`.
- **Multi-Camera VMS & Web Dashboard:**
  - `dashboard/stream_manager.py` *(Modified)*: Initialized `RSACManager`, `ActiveLearningManager`, `UniversalEnrollmentManager`. Added RSAC category colors to track bounding boxes, clutter warning banners, and clutter fields to telemetry.
  - `dashboard/camera_pool.py` *(Modified)*: Exposed `rsac_manager`, `active_learning`, `enrollment_manager` properties and `reload_all_galleries()`.
  - `dashboard/app.py` *(Modified)*: Mounted `/crops` directory. Added Pydantic schemas and REST endpoints for freeze-frame, universal enrollment, review queue triage actions, RSAC categories and rules CRUD, pet whitelist, descriptor version history, and rollback. Fixed JSON serialization of embedding vectors.
  - `dashboard/static/index.html` *(Modified)*: Added Review & Learn navigation tab, `✨ Enroll` header button, Review & Learn queue pane (`#tab-review`), Universal Freeze-Frame Enrollment modal (`#modal-universal-enrollment`), Descriptor Version History modal (`#modal-descriptor-versions`), Reassign modal (`#modal-review-reassign`), and Toast container (`#toast-container`).
  - `dashboard/static/review_and_rsac.js` *(New)*: Client-side controller for active learning triage, interactive freeze-frame canvas bounding box selection, version history rollback, and WebSocket toast notifications.
  - `dashboard/static/app.js` *(Modified)*: Tab switching hook for `tab-review`, version history trigger on entity cards in gallery, and WebSocket alert forwarding.
  - `dashboard/static/styles.css` *(Modified)*: Glassmorphism styles for review cards, confidence meters, category badge pills (`family_car`, `delivery_truck`, `cleaning_crew`, `guard_dog`, `pet`, `vip`, `restricted`), version history timeline, and toast notifications.
- **Unit & Integration Test Suites:**
  - `tests/test_rsac.py` *(New)*: 6 tests covering custom categories, schedule evaluation, allow/deny rules, entity overrides, and pet suppression.
  - `tests/test_active_learning.py` *(New)*: 5 tests covering candidate queueing, debouncing, confirm, reassign, enroll as new, and dismiss.
  - `tests/test_enrollment.py` *(New)*: 3 tests covering image crop enrollment, frame + bbox enrollment, and DualModelFeatureExtractor fusion.
  - `tests/test_occlusion_and_ema.py` *(New)*: 4 tests covering track occlusion IoU checks, clutter Re-ID freeze, bounded EMA adaptation, drift rejection, and version rollback.
  - `tests/test_m9_api.py` *(New)*: 4 tests covering FastAPI REST endpoints for freeze-frame, universal enrollment, review queue actions, RSAC rules/categories CRUD, and pet whitelist.
- **Documentation:**
  - `documentation/artifact_and_face_intelligence.rst` *(New)*: Comprehensive Sphinx documentation for Milestone 9.
  - `documentation/index.rst` *(Modified)*: Added `artifact_and_face_intelligence` to master documentation toctree.

### 3. Key Architectural Decisions
- **Dual-Model Embedding Fusion**: Artifact/body appearance (OSNet or color structure) and facial biometrics (YuNet) are fused into a single normalized vector. If a face is obscured or absent (e.g. vehicles, tools, packages, back-turned individuals), the facial subspace is cleanly zero-padded, maintaining dimensional consistency across all entities.
- **Role-Based Spatial Access Control (RSAC)**: Separates identification from authorization. An individual can be positively identified as "Staff" but still generate a critical breach alarm if entering the "Vault" outside business hours or if explicitly denied by an entity override.
- **Human-in-the-Loop Active Learning**: Instead of silently misidentifying individuals with ambiguous confidence ($0.45 \le \text{sim} < 0.70$), detections are debounced and routed to an operator triage queue. Operator confirmations create permanent ground-truth Locked Anchors that improve future recognition accuracy across all cameras.
- **Locked Anchors & Bounded EMA Updates**: Ground-truth enrollment crops are permanently protected against model drift. Running centroids adapt to lighting and perspective changes via EMA ($\alpha = 0.05$), but updates are strictly rejected if similarity to any locked anchor drops below $0.65$.
- **Track Occlusion Reasoning**: When bounding box $\text{IoU} > 0.3$, tracks are flagged as cluttered. Feature accumulation is held frozen during the interaction and only resumes after physical separation, preventing identity contamination and Re-ID swaps in crowded scenes.
- **Descriptor Version Snapshots & Rollback**: Every identity modification is recorded as an immutable version snapshot in SQLite. If poor lighting or occlusion ever corrupts an entity's profile, the operator can roll back to any prior verified version in one click.

### 4. State & Checkpoint
- **Status:** Milestone 9 COMPLETE (100% Green Unit Tests)
- **Automated Verification:**
  - Full test suite: `$env:MPLBACKEND='Agg'; python -m unittest discover tests`
  - Result: **Ran 209 tests in 20.477s — OK (0 failures, 0 errors, 100% passing)**.
  - Milestone 9 unit tests: `tests/test_rsac.py`, `tests/test_active_learning.py`, `tests/test_enrollment.py`, `tests/test_occlusion_and_ema.py`, `tests/test_m9_api.py` -> **22/22 OK (2.0s)**.
  - Sphinx Documentation: Built cleanly with **0 warnings** (`sphinx -W --keep-going documentation/ documentation/_build/html/`).

### 5. Verification Instructions
- **Windows (PowerShell):**
  ```powershell
  # 1. Run complete automated unit test suite (209 tests)
  $env:MPLBACKEND='Agg'; python -m unittest discover tests

  # 2. Run Milestone 9 dedicated test suites (22 tests)
  $env:MPLBACKEND='Agg'; python -m unittest -v tests.test_rsac tests.test_active_learning tests.test_enrollment tests.test_occlusion_and_ema tests.test_m9_api

  # 3. Build Sphinx documentation with zero warnings
  python -m sphinx -W --keep-going documentation/ documentation/_build/html/

  # 4. Launch Web Analytics, VMS & Active Learning Dashboard
  python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
  # Open $APP_URL (navigate to Review & Learn tab or click '✨ Enroll')
  ```
- **Linux / Raspberry Pi OS / macOS:**
  ```bash
  source .venv/bin/activate
  MPLBACKEND=Agg python -m unittest discover tests
  python -m unittest -v tests.test_rsac tests.test_active_learning tests.test_enrollment tests.test_occlusion_and_ema tests.test_m9_api
  python -m sphinx -W --keep-going documentation/ documentation/_build/html/
  python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
  ```











---
## Milestone 9.1: StreamManager Thread-Safety, Video Studio Fitting & Smart Docker Hibernation

### 1. Overview & Problem Diagnosis
During Phase 1B browser and container runtime audit, 4 interrelated operational issues were diagnosed and resolved:
1. **Camera Initializing Freeze on `cam_01` (Synthetic)**:
   - *Symptom*: Live Monitor permanently displayed "Camera Initializing...".
   - *Root Cause*: `StreamManagerWorker` crashed on startup with `RuntimeError: dictionary changed size during iteration` when iterating over `self.analytics.zones.values()` without snapshot shielding while startup scenarios dynamically populated zones.
2. **Video Studio Frame Overflow**:
   - *Symptom*: Videos in Video Studio exceeded the playback card frame, breaking bounds and triggering outer window scrollbars.
   - *Root Cause*: Grid column blow-out due to missing `min-width: 0` on `.video-player-card`, lack of `position: relative` on `.scrubber-viewport`, and insufficient vertical height budget (`calc(100vh - 280px)` didn't account for header, margins, and scrubber toolbar).
3. **Play/Pause Button State Desync on Load**:
   - *Symptom*: Switching videos via the "Load" button left the button displaying "Pause" even though the new video was paused at frame 0.
   - *Root Cause*: Missing explicit pause lifecycle in `loadVideoIntoPlayer()`, allowing asynchronous media promise resolution and out-of-order `play` events to re-toggle button text.
4. **Severe Docker CPU & Network Drain (336% CPU / 128 Threads)**:
   - *Symptom*: `intelligent-tracker-dashboard` was consuming 300%+ CPU and transferring gigabytes of background video data.
   - *Root Cause*: Background video streams (`vid_*`) decoded 2K/4K HEVC frames at 30+ FPS non-stop even when zero clients were subscribed or viewing.

### 2. Files Touched
- `dashboard/stream_manager.py`:
  - Protected all zone and tripwire iterations with `list(...)` snapshots.
  - Implemented thread-safe `_subscriber_count`, `add_subscriber()`, `remove_subscriber()`, and `subscriber_count`.
  - Added Smart Hibernation in `_worker_loop`: idle-sleeps (`time.sleep(0.1)`) when `subscriber_count == 0` after initial frame generation, instantly resuming upon viewer connection.
- `dashboard/app.py`:
  - Hooked `add_subscriber()` / `remove_subscriber()` into `/stream/{camera_id}` MJPEG streaming generator and `/ws/{camera_id}` WebSocket lifecycles.
- `dashboard/static/styles.css`:
  - Added `min-width: 0` to `.video-player-card` and `minmax(0, 1fr)` to `.scrubber-grid`.
  - Adjusted `.scrubber-viewport` height budget to `max-height: min(calc(100vh - 350px), 62vh)` with `position: relative` and containment styling.
  - Added styles for `.scrubber-tab-policy-group` dropdown in the controls row.
- `dashboard/static/index.html`:
  - Added tab-switching policy dropdown (`Auto-Pause & Resume`, `Pause & Hold`, `Pause & Reset`) to the Video Studio controls row.
- `dashboard/static/video_scrubber.js`:
  - Explicitly invokes `videoPlayer.pause()`, resets `videoPlayer.currentTime = 0`, and syncs `btnPlayPause.textContent = '▶ Play'` in `loadVideoIntoPlayer()`.
  - Added `onTabLeave()` and `onTabEnter()` lifecycle methods handling user-selected tab policy.
  - Persisted user preference in `localStorage`.
- `dashboard/static/app.js`:
  - Hooked `switchTab()` to trigger `VideoScrubber.onTabLeave()` / `VideoScrubber.onTabEnter()`.
  - Automatically disconnects/restores `live-stream-img.src` when switching away from `tab-live` to trigger Docker backend Smart Hibernation.
  - Added Page Visibility API handler (`document.addEventListener('visibilitychange')`) to pause/resume playback on window minimize/restore.

### 3. Verification & Metrics
- **Automated Unit Tests**: Ran 209 unit tests via `python -m unittest discover tests` -> **209/209 OK (100% green)**.
- **Docker Resource Audit**: Ran `docker_audit.py` -> Container CPU dropped from **336.20% down to ~30%**; thread count dropped from **128 down to 79-81**; zero Tracebacks/Errors.
- **Headless Chrome CDP Audit**:
  - Ran `cdp_inspect.py` -> Verified `cam_01` synthetic feed is streaming properly (`naturalWidth: 640`, `naturalHeight: 480`).
  - Verified Video Studio video fits completely inside `.scrubber-viewport` without overflow (`video_studio_verified.jpg`).
  - Verified clicking "Load" switches videos, pauses at 0:00, and displays "▶ Play" (`pausedAfterLoad: true`, `textAfterLoad: '▶ Play'`).
  - Verified all 3 tab-switching policies (`auto-resume`, `keep-paused`, `reset`) activate and persist correctly.
- **Documentation**: Built Sphinx documentation cleanly with **0 warnings** (`sphinx -W --keep-going documentation/ documentation/_build/html/`).

---
## [Milestone 10] - 2026-10-28 - VMS Dashboard Responsive Redesign, Ergonomics & Enterprise Hub Integration Readiness

### 1. Objectives & Scope
- Comprehensive empirical audit and redesign of the VMS Dashboard web application (`dashboard/static/`):
  1. **Responsiveness & Horizontal Overflow**: Diagnose and eliminate 1729px horizontal viewport overflow on desktop/tablets/mobile; add mobile slide-out navigation drawer (<1024px) with smooth snap-scrolling tab pill bar.
  2. **Dialog & Modal Scroll Containment**: Constrain `.modal-card` to `max-height: min(88dvh, 800px)` with internal `.modal-body-scroll` container and `overscroll-behavior: contain`. Fix form clipping in "Multi-Camera VMS & Device Auto-Discovery" dialog.
  3. **Ergonomics & In-Page Modal Forms**: Eliminate cumbersome sequential browser `prompt()` and `confirm()` alert chains in Scenario Studio and Review & Learn, replacing them with dedicated in-page modal dialog forms (Zone, Tripwire, Homography, Spatial Transitions, Quick-Enroll) and non-blocking toast notifications (`showToast()`).
  4. **Live Monitor Stream Reconnect**: Fix broken image bug caused by `img.src = ''` resolving to document URL; detach stream via standby SVG poster and reconnect with cache-buster `?t=${Date.now()}` on tab return.
  5. **Unified VMS Player Architecture**: Add modern Live Player HUD matching Video Studio (live status badge, stream pause/resume button, snapshot, fullscreen, telemetry HUD).
  6. **Bidirectional URL Hash Routing**: Client-side hash routing supporting `#live`, `#videos`, `#gallery`, `#timeline`, `#analytics`, `#alerts`, `#studio`, `#journey`, `#review`, and modal sub-routes `#cameras`, `#enroll`, `#backup`, `#versions` with full browser Back/Forward navigation (`popstate`/`hashchange`).
  7. **Enterprise Hub Integration Alignment (Milestone 16d / Phase E5)**:
     - Edge-to-Hub Security Webhook HMAC-SHA256 signing (`X-Tracker-Signature`).
     - REST Telemetry snapshot endpoint `GET /api/cameras/{camera_id}/telemetry` for Hub HTML5 Canvas overlays.
     - Offline SQLite cache schema (`tracker_sync_state`, `local_whitelist`, `offline_access_queue`) per `INTELLIGENT_TRACKER_OFFLINE_DB_SPEC.md`.
  8. **Automated Layout & Regression Tests**: Add `tests/test_dashboard_ui.py` and automated headless Chrome CDP layout verification across desktop, tablet, and mobile presets.

### 2. Files Touched / Created
- `INTELLIGENT_TRACKER_OFFLINE_DB_SPEC.md`: Authored offline-first SQLite cache schema specification, delta-sync lifecycle, and Cloud Hub webhook/telemetry contracts.
- `milestone_plan.md`: Added Milestone 10 specification, deliverable breakdown, and updated status to COMPLETE.
- `MIGRATION_LOG.md`: Recorded Milestone 10 architecture decisions, empirical findings, and integration alignment.
- `documentation/enterprise_hub_integration.rst`: Authored comprehensive Sphinx documentation detailing Edge-to-Hub protocols, HMAC-SHA256 webhooks, zero-copy video streaming, telemetry endpoints, and offline cache synchronization.
- `documentation/dashboard.rst`: Added Milestone 10 responsive architecture documentation, Live Player HUD, bidirectional hash routing, modal scroll containment, and an executable scenario combinations matrix.
- `documentation/index.rst`: Registered `enterprise_hub_integration` in master documentation toctree.
- `intelligent_tracker/events.py`: Implemented HMAC-SHA256 webhook signatures (`X-Tracker-Signature`), UTC ISO-8601 timestamps, epoch floats, and Base64 evidence snapshots in `WebhookDispatcher`.
- `intelligent_tracker/database.py`: Conformed SQLite schema to `INTELLIGENT_TRACKER_OFFLINE_DB_SPEC.md` with tables `tracker_sync_state`, `local_whitelist`, `offline_access_queue` and DAO methods.
- `dashboard/app.py`: Implemented `GET /api/cameras/{camera_id}/telemetry` endpoint returning real-time bounding boxes, active tracks, and zone states for Cloud Hub overlay proxying.
- `dashboard/static/index.html`: Responsive header with auto-scrolling `nav-tabs-wrapper`, hamburger button, mobile drawer (`mobile-nav-drawer`), in-page modal dialog forms, Live Player HUD, and toast container.
- `dashboard/static/styles.css`: Modal scroll containment (`overscroll-behavior: contain`), sticky footer, responsive breakpoints (1280px, 1024px, 768px), mobile drawer, HUD toolbar styles, and `minmax(0, 1fr)` / `min-width: 0` horizontal overflow containment.
- `dashboard/static/app.js`: Modern toast system (`showToast`), standby poster stream lifecycle, Live Player HUD button handlers, mobile drawer toggle, and bidirectional URL hash router.
- `dashboard/static/studio.js`: Wired in-page modal dialogs for zones, tripwires, homography, transitions; eliminated browser `prompt()` alert chains; replaced `alert()` with `showToast()`.
- `dashboard/static/review_and_rsac.js`: Wired quick enrollment modal; replaced `alert()` with `showToast()`.
- `dashboard/static/camera_manager.js`: Replaced blocking `alert()` popups with `showToast()`.
- `dashboard/static/video_scrubber.js`: Replaced blocking `alert()` popups with `showToast()`.
- `scripts/cdp_inspect.py`: Cross-platform headless Chrome CDP browser inspector.
- `tests/test_database.py`: Added tests for sync state, local whitelist CRUD, and offline access queue.
- `tests/test_events.py`: Added tests for HMAC-SHA256 webhook signatures and ISO-8601 timestamps.
- `tests/test_dashboard_ui.py`: Created 5 tests covering HTML structure, modal containment, static asset delivery, and telemetry snapshot API.

### 3. State & Checkpoint
- **Status:** Milestone 10 COMPLETE (100% Green Unit Tests & CDP Layout Verification)
- **Unit Test Suite:** 218 tests passing in 22.997s (100% green, 0 failures, 0 errors).
- **Sphinx Documentation:** Built successfully with **0 warnings** (`python -m sphinx -W --keep-going documentation/ documentation/_build/html/`).
- **CDP Headless Layout Audit:**
  - Desktop (1440x900): `scrollWidth: 1425 <= 1440`, `hasHorizontalScrollbar: false`, 0 layout overflow warnings.
  - Tablet (768x1024): `scrollWidth: 753 <= 768`, `hasHorizontalScrollbar: false`, 0 layout overflow warnings.
- **Enterprise Hub Integration Alignment:** Fully verified against `INTELLIGENT_TRACKER_INTEGRATION_PLAN.md` Phase E5.




---
## [2026-10-28] - Viewport Sizing, Interactive Canvas Alignment & Multi-Grid Fullscreen Modernization

### 1. Objectives & Scope
- Resolve issue where 1x1 camera feed was constrained to intrinsic 640x480 dimensions instead of filling `.video-container`.
- Fix `#interactive-canvas` inline dimension and offset overrides, achieving mathematical coordinate alignment over the active video frame.
- Restore flexbox centering in `camera_manager.js` when switching between 1x1 and multi-camera grids.
- Add CSS `:fullscreen` rules and universal `toggleFullscreen()` controller supporting both 1x1 and 2x2/3x3 multi-grid layouts with `ResizeObserver` reactivity.

### 2. Files Modified
- `dashboard/static/styles.css`: Updated `#live-stream-img` to `width: 100%; height: 100%; object-fit: contain;`. Added `:fullscreen` overrides for `.video-container` and `.multi-camera-grid`.
- `dashboard/static/app.js`: Refactored `syncCanvasSize()` with pillarbox/letterbox aspect-ratio math; updated tooltip positioning to respect canvas offset; implemented unified `toggleFullscreen()`; registered `ResizeObserver` on container and stream image; bound `fullscreenchange` listener on `document`.
- `dashboard/static/camera_manager.js`: Set `singleVideoWrapper.style.display = 'flex'` on 1x1 grid switch and dispatched resize event.

### 3. Empirical Verification
- **Unit Tests**: Full test suite passing (218 tests in 23.058s, 100% green).
- **Headless CDP Layout Audit (`scripts/cdp_inspect.py`)**:
  - 1x1 Mode: `#video-wrapper` 979x551, `#live-stream-img` 977x549 (fully expanded), `#interactive-canvas` 732x549 centered at x=165 with exact 4:3 parity.
  - Multi-Grid Switch: Clean transition to 2x2 (`#multi-grid-container` 979x551, 4 tiles rendering with `object-fit: cover`), and back to 1x1 (`display: flex`).
  - Fullscreen Target: Confirmed polymorphic resolution (`video-wrapper` in 1x1, `multi-grid-container` in 2x2).


---
## [2026-10-28] - Aspect-Ratio Preservation, Fullscreen Player Hardening & Header Overflow Fix

### 1. Objectives & Scope
- Preserve native 16:9 / 4:3 video source aspect ratios during stream acquisition in `VideoSource` without forced distortion to 4:3 (640x480).
- Eliminate all `!important` declarations from CSS fullscreen rules, relying on natural pseudo-class specificity.
- Fullscreen `.video-card` as a unified player root so transitioning between 3x3/2x2 and 1x1 within fullscreen occurs seamlessly with zero page bleed.
- Eliminate header horizontal overflow caused by unconstrained `<select id="active-camera-select">` and long stream titles.

### 2. Files Modified
- `intelligent_tracker/video.py`: Proportional envelope downscaling in `VideoSource` preserving native source aspect ratio (e.g. 2688x1520 -> 640x362, 25% lower pixel processing load).
- `dashboard/stream_manager.py`: Bound `AnalyticsEngine` resolution dynamically to `(self.video_source.width, self.video_source.height)`.
- `dashboard/static/styles.css`: Removed all `!important` flags. Applied `.video-card:fullscreen` player rules. Added `max-width: 240px` and text ellipsis on `.camera-select-wrapper` and `.form-select-sm`. Enforced `flex: 1 1 auto; min-width: 0; text-overflow: ellipsis;` on `.card-title` and `#video-stream-title`.
- `dashboard/static/index.html`: Added `id="live-video-card"` to `.video-card`.
- `dashboard/static/app.js`: Updated `toggleFullscreen()` to target `#live-video-card`.
- `dashboard/static/camera_manager.js`: Set `title` attribute on `#video-stream-title` for full tooltip reveal on hover.

### 3. Empirical Verification
- **Video Resolution**: Stream `vid_20260912132121211_92c53f9523ac476689854669f9750d9e_G94106186` (native 2688x1520) outputs 640x362 at 30.3 FPS with aspect ratio 1.768 (16:9 match).
- **DOM Layout**: `#interactive-canvas` width: 970.6px, height: 549px across 977px image frame (zero black bars, full frame utilization).
- **Header Overflow**: `.card-actions` width decreased from 1470px to 680px; `#video-stream-title` truncates with ellipsis; `hasHorizontalOverflow: false`.
- **Unit Tests**: 218 tests passing in 23.725s (100% green).
- **Documentation**: Sphinx build succeeded with 0 warnings.


---
## [Milestone 10] - 2026-10-29 - Process Lifecycle Management, Zero-Load Hibernation & Runtime Diagnostics

### 1. Objectives & Scope
- Resolve critical container CPU leak (270% CPU across 130 threads) caused by silent Uvicorn disconnects, unmanaged MJPEG generator tasks, and monotonic subscriber counter drift.
- Implement deep hardware and video capture hibernation in `VideoSource` (`pause()` and `resume()`) to drop OpenCV frame decoding to 0.0 FPS when no active viewers are present.
- Create a self-healing, TTL-leased subscriber registry (`_subscribers: Dict[str, float]`) in `StreamManager` with auto-eviction of stale client leases after 3.0 seconds of inactivity.
- Implement async disconnect detection (`await request.is_disconnected()`) in `dashboard/app.py` `/stream/{camera_id}` with guaranteed cleanup in `finally:`.
- Add clean unload lifecycle handlers (`beforeunload`, `pagehide`) in frontend JavaScript (`app.js` and `camera_manager.js`) to tear down MJPEG streams and WebSocket connections on tab close or background switch.
- Modernize `docker-compose.yml` to put standalone headless `tracker` worker behind `profiles: ["worker"]` and disable spurious HTTP healthchecks.
- Enrich `scripts/diagnostics.py` with runtime Docker container stats, active stream states, and zombie task detection flags (`--runtime`, `--hardware`, `--url`).
- Build cross-platform CLI tool `scripts/stream_ctl.py` for operators (`list`, `stats`, `evict`, `prune`, `history`, `metrics`).
- Create `intelligent_tracker/lifecycle.py` (`StreamLifecycleManager`) with background telemetry sampling daemon persisting metrics to SQLite (`TrackerDB` tables `system_resource_metrics` and `stream_lifecycle_events`).
- Expose Superuser Admin REST APIs:
  - `GET /api/system/processes`: Full thread, PID, memory, and stream state breakdown.
  - `POST /api/system/streams/{camera_id}/evict`: Force-evict subscriber leases and trigger immediate hibernation.
  - `POST /api/system/hibernate_all`: Force-hibernate any idle channels.
  - `GET /api/system/metrics`: Historical resource usage time-series.
  - `GET /api/system/events`: Historical stream lifecycle audit trail.

### 2. Files Touched / Created
- `intelligent_tracker/video.py`: Added thread-safe `pause()`, `resume()`, `is_paused`, and updated `_capture_worker` and `stop()`.
- `dashboard/stream_manager.py`: Implemented leased subscriber registry, TTL auto-pruning, deep hibernation state transitions, and unified `_subscriber_lock`.
- `dashboard/app.py`: Added `Request` async disconnect guard in `get_live_stream`, integrated `StreamLifecycleManager`, and added admin REST APIs.
- `dashboard/static/app.js`: Added `beforeunload` and `pagehide` listeners to detach live streams on navigation.
- `dashboard/static/camera_manager.js`: Detached background grid images in 1x1 mode to prevent background stream holding.
- `docker-compose.yml`: Added `profiles: ["worker"]` and `healthcheck: disable: true` to `tracker` service.
- `intelligent_tracker/database.py`: Created tables `system_resource_metrics` and `stream_lifecycle_events` and data access methods.
- `intelligent_tracker/lifecycle.py`: Created `StreamLifecycleManager` with telemetry sampling daemon.
- `scripts/diagnostics.py`: Enriched with runtime process, Docker container, and stream hibernation checks.
- `scripts/stream_ctl.py`: Created terminal CLI controller for stream and process lifecycle management.
- `tests/test_hibernation.py`: Added 5 unit tests for VideoSource pause/resume and leased subscriber registry.
- `tests/test_lifecycle.py`: Added 6 unit tests for StreamLifecycleManager and admin REST APIs.

### 3. Empirical Verification & Performance Metrics
- **Container CPU**: Dropped from **267.31%** down to **0.66%** in Docker stats when idle (over 400x reduction).
- **Stream State**: 4 inactive camera feeds verified at 0.0 FPS in deep hibernation; primary feed hibernates cleanly upon disconnect or eviction.
- **Eviction Test**: `python scripts/stream_ctl.py evict cam_01` successfully evicted leases, forced state transition to `HIBERNATING`, and recorded audit event.
- **Full Test Suite**: 223 out of 223 unit and integration tests passing (100% green).
- **Documentation**: Sphinx build verified with 0 warnings.


---
## [Milestone 12] - 2026-10-30 - Dashboard Architecture & Domain Services Decoupling (Phase 1)

### 1. Objectives & Scope
- Initiate architectural decomposition of `dashboard/` subsystem in accordance with `/refactor-monolith` and `/frontier-architect` quantitative modularity budgets.
- Extract cold collaborator services from `dashboard/stream_manager.py` (exceeded 880 lines) into dedicated domain services under `dashboard/services/`.
- Guarantee **Zero-Copy Hot Path**: OpenCV inference loop (`StreamManager._worker_loop`) processes video frames directly on NumPy arrays without IPC, thread hopping, or serialization overhead.
- Guarantee **Deep Hibernation Preservation**: `StreamSubscriberRegistry` manages leased subscriber tokens with 3.0s lease TTL, triggering `VideoSource.pause()` when subscriber count hits zero (< 1% idle container CPU).
- Prepare first-class architectural seams for Enterprise Hub integration (Conversation ID `c2969330-7f3b-4ab1-afd2-9ddebcab2e2a`): REST telemetry polling (`GET /api/cameras/{camera_id}/telemetry`), HMAC alert signing, and offline SQLite delta sync.
- Establish baseline contract snapshot (`.refactor_baseline.json`) and permanent contract smoke test (`tests/test_refactor_contract.py`).

### 2. Files Touched / Created
- `dashboard/services/__init__.py`: Package export for domain services.
- `dashboard/services/stream_subscribers.py` (126 lines): `StreamSubscriberRegistry` extracting leased viewer tokens, TTL 3.0s auto-pruning, and hibernation pause/resume callbacks.
- `dashboard/services/frame_overlay.py` (160 lines): `FrameOverlayRenderer` extracting HUD annotations, bounding boxes, dwell timers, velocity vectors, and zone polygons.
- `dashboard/services/video_transcoder.py` (113 lines): `VideoTranscodeService` extracting ffprobe inspection and ffmpeg transcoding.
- `dashboard/services/entity_tagger.py` (137 lines): `EntityTaggerService` extracting click-to-tag bounding box visual crop, Re-ID embedding, and SQLite signature registration.
- `dashboard/stream_manager.py`: Shrunk from 880 lines to 680 lines (eliminated 200 lines from the monolith) via facade delegation, maintaining 100% backward compatibility for all 25 public methods/properties.
- `tests/test_refactor_contract.py`: Automated contract smoke test enforcing DOM `<select>` dropdown and CSS `!important` parity.
- `scripts/code_health_audit.py`, `scripts/contract_snapshot.py`, `scripts/surface_scanners.py`: Portable structural audit and contract verification CLI tools.
- `dashboard_refactor_plan.md`: Complete 4-phase architectural roadmap with 1-phase turn gates.

### 3. Empirical Verification & Modularity Audit
- **Modularity Budgets Achieved**:
  - `dashboard/services/frame_overlay.py`: 160 lines (Target: $\le$ 350L).
  - `dashboard/services/entity_tagger.py`: 137 lines (Target: $\le$ 350L).
  - `dashboard/services/stream_subscribers.py`: 126 lines (Target: $\le$ 350L).
  - `dashboard/services/video_transcoder.py`: 113 lines (Target: $\le$ 350L).
  - `dashboard/services/__init__.py`: 19 lines (Target: $\le$ 350L).
  - `dashboard/stream_manager.py`: 680 lines (reduced from 880 lines, -200 lines).
- **Automated Regression Test Suite**:
  - `python -m unittest discover tests`
  - Result: **Ran 231 tests in 21.892s — OK (0 failures, 0 errors)**.
- **Hardware Hibernation Verification**:
  - `python -m unittest tests/test_hibernation.py tests/test_lifecycle.py`
  - Result: **Ran 11 tests in 2.859s — OK (0 failures, 0 errors)**.
- **Contract Smoke Test**:
  - `python -m unittest tests/test_refactor_contract.py`
  - Result: **Ran 2 tests in 0.006s — OK (0 failures, 0 errors)**.
- **Documentation Build**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`
  - Result: **Build succeeded with 0 warnings**.

### 4. Next Phase
- Phase 2: Backend API Routers & App Factory Decoupling (`dashboard/dependencies.py`, `dashboard/schemas.py`, `dashboard/routers/`, App Factory in `dashboard/app.py`).


---
## [Milestone 13] - 2026-10-30 - Dashboard API Routers & App Factory Decoupling (Phase 2)

### 1. Objectives & Scope
- Decompose the monolithic FastAPI web application in `dashboard/app.py` (previously 1,951 lines and 76 endpoints) into a clean, modular router architecture adhering strictly to quantitative modularity budgets ($\le$ 350 lines soft target, $\le$ 500 lines hard ceiling, $\le$ 40 lines per function, $\le$ 15–25 lines per endpoint handler).
- Establish `dashboard/dependencies.py` implementing the **Bidirectional Proxy Pattern** for `camera_pool`, `stream_manager`, `scenario_manager`, and `lifecycle_manager`, ensuring 100% compatibility with test fixtures that dynamically monkeypatch module-level globals on `dashboard.app`.
- Consolidate all 21 request/response Pydantic models into `dashboard/schemas.py` with full re-export facades on `dashboard.app`.
- Extract 8 cohesive domain `APIRouter` modules under `dashboard/routers/`:
  1. `system.py`: Hardware status, system diagnostics, process management, stream eviction, and database backup export/import.
  2. `cameras.py`: Multi-camera pool CRUD, hardware discovery, presets, overlays, freeze frame, and **`GET /api/cameras/{camera_id}/telemetry`** for central Enterprise Hub canvas overlay proxying.
  3. `streaming.py`: Live MJPEG video stream with low-latency `await request.is_disconnected()` guard and real-time bi-directional telemetry WebSockets.
  4. `scenarios.py`: Polygonal zones, directional tripwires, 4-point homography ground plane calibration, and Bird's-Eye-View (BEV) minimap rendering.
  5. `rsac.py`: Universal Entity Enrollment, Human-in-the-Loop Active Learning Review Queue, custom category badges, RSAC zone rules, pet alarm suppression whitelist, and visual descriptor version history/rollback.
  6. `analytics.py`: Spatial density heatmaps, gallery identity CRUD, Re-ID sighting history, EventBus alerts, click-to-tag bounding box enrollment, and crop thumbnail serving.
  7. `videos.py`: Local video recording management, uploads with auto-transcode, H.264 transcoding delegation, offline batch indexing, and HTML5 video streaming.
  8. `topology.py`: Cross-camera spatial transition links, active predictive Re-ID priors, and multi-camera trajectory journey search/video export.
- Convert `dashboard/app.py` into a thin FastAPI App Factory (`create_app()`, 233 lines) maintaining 100% backward compatibility for all module globals, helper functions, and Pydantic schemas.

### 2. Files Touched / Created
- `dashboard/dependencies.py` (236 lines): Bidirectional proxy bridge and typed dependency providers (`get_camera_pool`, `get_stream_manager`, `get_scenario_mgr`, `get_lifecycle_manager`, `get_db`, `get_rsac_mgr`, `get_active_learning_mgr`, `get_enrollment_mgr`, `reload_all_galleries`).
- `dashboard/schemas.py` (184 lines): Validated Pydantic models for cameras, zones, tripwires, homography, RSAC access control, and active learning candidate reviews.
- `dashboard/routers/__init__.py` (37 lines): Package facade exposing all 8 domain routers.
- `dashboard/routers/system.py` (155 lines): System health, backup export/import, and process eviction router.
- `dashboard/routers/cameras.py` (298 lines): Camera pool CRUD, discovery, telemetry, and overlays router.
- `dashboard/routers/streaming.py` (126 lines): MJPEG live streaming and WebSockets router.
- `dashboard/routers/scenarios.py` (271 lines): Zones, tripwires, homography, and BEV minimap router.
- `dashboard/routers/rsac.py` (299 lines): RSAC access rules, enrollment, active learning, and version rollback router.
- `dashboard/routers/analytics.py` (267 lines): Heatmap, entities, sightings, and event alerts router.
- `dashboard/routers/videos.py` (242 lines): Video management, uploads, transcoding, and scrubber router.
- `dashboard/routers/topology.py` (166 lines): Spatial transitions and multi-camera journey router.
- `dashboard/app.py` (233 lines): Shrunk from 1,951 lines down to 233 lines (-1,718 lines / 88% reduction) as a clean App Factory and backward-compatible facade.
- `.refactor/state.json`: Advanced campaign from Phase 2 to Phase 3.

### 3. Empirical Verification & Modularity Audit
- **Modularity Budgets Achieved (All 12 Files Healthy / 0 Critical / 0 Warning)**:
  - `dashboard/app.py`: 233 lines (Target: $\le$ 350L, reduced from 1,951 lines).
  - `dashboard/dependencies.py`: 236 lines (Target: $\le$ 350L).
  - `dashboard/schemas.py`: 184 lines (Target: $\le$ 350L).
  - `dashboard/routers/rsac.py`: 299 lines (Target: $\le$ 350L).
  - `dashboard/routers/cameras.py`: 298 lines (Target: $\le$ 350L).
  - `dashboard/routers/scenarios.py`: 271 lines (Target: $\le$ 350L).
  - `dashboard/routers/analytics.py`: 267 lines (Target: $\le$ 350L).
  - `dashboard/routers/videos.py`: 242 lines (Target: $\le$ 350L).
  - `dashboard/routers/topology.py`: 166 lines (Target: $\le$ 350L).
  - `dashboard/routers/system.py`: 155 lines (Target: $\le$ 350L).
  - `dashboard/routers/streaming.py`: 126 lines (Target: $\le$ 350L).
  - `dashboard/routers/__init__.py`: 37 lines (Target: $\le$ 350L).
  - All functions across all routers and dependencies: $\le$ 40 lines (100% compliant).
- **Contract Parity & Zero Regression Diff**:
  - `python scripts/contract_snapshot.py verify --path dashboard --strict`
  - Result: **OK: Zero contract regressions detected! (DOM IDs, selects, globals, routes, and CSS preserved)**. All 76 backend routes intact.
- **Contract Smoke Test**:
  - `python -m unittest tests/test_refactor_contract.py`
  - Result: **Ran 2 tests in 0.007s — OK (0 failures, 0 errors)**.
- **API & Lifecycle Integration Suites**:
  - `python -m unittest tests/test_dashboard.py tests/test_scenario_api.py tests/test_vms_api.py tests/test_m9_api.py tests/test_lifecycle.py`
  - Result: **Ran 33 tests in 9.476s — OK (0 failures, 0 errors)**.
- **Full Automated Regression Suite**:
  - `python -m unittest discover tests`
  - Result: **Ran 231 tests in 27.169s — OK (0 failures, 0 errors)**.
- **Sphinx Documentation Build**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`
  - Result: **Build succeeded with 0 warnings**.

### 4. Next Phase
- Phase 3: Frontend Modular ITCSS Stylesheets (`dashboard/static/styles.css` decomposed into modular layers with 0 `!important`).


---
## [Milestone 14] - 2026-10-30 - Frontend Modular ITCSS Stylesheets Decomposition (Phase 3)

### 1. Objectives & Scope
- Decompose the monolithic stylesheet in `dashboard/static/styles.css` (previously 2,902 lines) into a clean, modular ITCSS (Inverted Triangle CSS) layered architecture strictly adhering to quantitative modularity budgets (150–300 lines healthy target, $\le$ 350 lines soft ceiling, $\le$ 500 lines hard ceiling).
- Enforce strict project CSS guidelines: eliminate all legacy occurrences of `!important` (previously 4 items in baseline) using natural specificity hierarchies (`.studio-toolbar .studio-tool-btn.active`, `.btn.studio-tool-btn.active`, `.video-card:fullscreen .video-container`), avoiding specificity debt.
- Structure stylesheets into 16 cohesive domain partials under `dashboard/static/css/`:
  1. `tokens.css` (70 lines): `:root` design tokens, color palette, typography, glassmorphism panel styles.
  2. `components.css` (81 lines): Buttons (`.btn`, `.btn-primary`, `.btn-outline`), form inputs, and empty states.
  3. `badges.css` (81 lines): Category pills (`staff`, `vip`, `restricted`, `family_car`, `delivery_truck`, `cleaning_crew`, `guard_dog`, `pet`) and hardware interface badges (`badge-usb`, `badge-onvif`).
  4. `layout.css` (289 lines): App header, branding, horizontal scroll-snapped nav tabs, main container shell.
  5. `drawer.css` (121 lines): Mobile slide-out navigation drawer with smooth cubic-bezier transitions.
  6. `sidebar.css` (194 lines): KPI analytics metrics, zone status bars, tripwire tallies, and live security alerts list.
  7. `player.css` (286 lines): Live video player card, `:fullscreen` modes, interactive annotation canvas, and live player HUD toolbar.
  8. `vms_grid.css` (182 lines): Multi-camera matrix grid container (`grid-2x2`, `grid-3x3`), matrix switcher, and camera grid tiles.
  9. `views.css` (323 lines): Entity gallery grid, sighting timeline stream, density heatmaps, and security alerts table.
  10. `scrubber.css` (196 lines): Video studio playback scrubber, HTML5 video player, speed controls, and video library list.
  11. `studio.css` (221 lines): Scenario Studio toolbar, drawing canvas, floating overlay chips, and Bird's-Eye-View (BEV) minimap.
  12. `topology.css` (163 lines): Spatial topology link flow cards and multi-camera trajectory journey hops timeline.
  13. `review.css` (211 lines): Active learning review queue inbox, candidate confidence meters, action buttons, and version history timeline.
  14. `modals.css` (267 lines): Standardized dialog architecture with scrollable bodies, camera manager modal, and backup manager dialog.
  15. `toast.css` (88 lines): Floating toast notifications with keyframe slide animations.
  16. `responsive.css` (117 lines): Global media breakpoints (1280px, 1080px, 1024px, 768px).
- Convert `dashboard/static/styles.css` into a lean 35-line ITCSS master entrypoint with ordered `@import` statements preserving 100% backward compatibility for `<link rel="stylesheet" href="/static/styles.css">`.
- Update `tests/test_dashboard_ui.py` to verify that all imported ITCSS modules resolve with HTTP 200 and that all responsive modernization classes are present across the stylesheet cascade.
- Advance campaign state in `.refactor/state.json` from Phase 3 to Phase 4.

### 2. Files Touched / Created
- `dashboard/static/css/tokens.css` (70 lines)
- `dashboard/static/css/components.css` (81 lines)
- `dashboard/static/css/badges.css` (81 lines)
- `dashboard/static/css/layout.css` (289 lines)
- `dashboard/static/css/drawer.css` (121 lines)
- `dashboard/static/css/sidebar.css` (194 lines)
- `dashboard/static/css/player.css` (286 lines)
- `dashboard/static/css/vms_grid.css` (182 lines)
- `dashboard/static/css/views.css` (323 lines)
- `dashboard/static/css/scrubber.css` (196 lines)
- `dashboard/static/css/studio.css` (221 lines)
- `dashboard/static/css/topology.css` (163 lines)
- `dashboard/static/css/review.css` (211 lines)
- `dashboard/static/css/modals.css` (267 lines)
- `dashboard/static/css/toast.css` (88 lines)
- `dashboard/static/css/responsive.css` (117 lines)
- `dashboard/static/styles.css` (35 lines, reduced from 2,902 lines)
- `tests/test_dashboard_ui.py`: Updated asset integrity check to resolve and verify `@import` rules.
- `tests/test_refactor_contract.py`: Updated contract smoke test.
- `.refactor/state.json`: Advanced campaign to Phase 4 (active).
- `.refactor/plan.md` & `dashboard_refactor_plan.md`: Updated Phase 3 to completed status.

### 3. Empirical Verification & Modularity Audit
- **Modularity Budgets Achieved (All 17 Stylesheet Files Healthy / 0 Critical / 0 Warning)**:
  - Every single CSS file is $\le$ 323 lines (100% compliant with 350L soft warning and 500L hard ceiling).
  - `dashboard/static/styles.css`: 35 lines (98.8% line reduction).
  - All functions / rules / media queries: $\le$ 40 lines (100% compliant).
- **CSS Specificity Standard**:
  - `!important` count: **0** across all stylesheets (down from 4 items, 100% eliminated).
- **Contract Parity & Zero Regression Diff**:
  - `python scripts/contract_snapshot.py verify --path dashboard --strict`
  - Result: **OK: Zero contract regressions detected! (DOM IDs, selects, globals, routes, and CSS preserved)**.
- **Contract Smoke Test**:
  - `python -m unittest tests/test_refactor_contract.py`
  - Result: **Ran 3 tests in 0.013s — OK (0 failures, 0 errors)**.
- **Frontend Dashboard UI Suite**:
  - `python -m unittest tests/test_dashboard_ui.py`
  - Result: **Ran 5 tests in 0.386s — OK (0 failures, 0 errors)**.
- **Full Automated Regression Suite**:
  - `python -m unittest discover tests`
  - Result: **Ran 232 tests in 29.225s — OK (0 failures, 0 errors)**.
- **Sphinx Documentation Build**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`
  - Result: **Build succeeded with 0 warnings**.

### 4. Next Phase
- Phase 4: Frontend Modular Feature Modules & Contracts (`dashboard/static/app.js`, `studio.js`, `review_and_rsac.js`, `video_scrubber.js`, `camera_manager.js` decomposed into modular feature controllers under `dashboard/static/js/` preserving all `window.*` globals).


---
## [2026-10-31] - Milestone 15: Phase 4 Dashboard Monolith Decomposition (Client-Side JS Modularization) & Campaign Completion

### 1. Objectives & Scope
- Decompose all client-side JavaScript "God Files" (`dashboard/static/app.js`, `studio.js`, `review_and_rsac.js`, `video_scrubber.js`, `camera_manager.js`) to achieve 100% compliance with quantitative modularity budgets ($\le$ 350 lines soft ceiling, $\le$ 500 lines hard ceiling).
- Extract 18 cohesive domain submodules into `dashboard/static/js/` without introducing external node/npm build dependencies or runtime bundle overhead.
- Guarantee 100% invariant preservation across all DOM IDs (256/256), interactive `<select>` dropdowns (15/15), and global `window.*` API contracts (`window.App`, `window.CameraManager`, `window.ReviewAndRSAC`, `window.Studio`, `window.VideoScrubber`, `window.showToast`, etc.).
- Complete all 4 phases of the dashboard modernization campaign in `.refactor/state.json`.

### 2. Files Created & Modified
- **New Modular JavaScript Submodules** (`dashboard/static/js/`):
  - `video_batch.js` (85 lines) — Batch analytics report generation and progress tracking.
  - `video_library.js` (189 lines) — Video listing, uploads, transcode notices, camera pool addition.
  - `camera_discovery.js` (213 lines) — USB device scanning, ONVIF discovery, preset URL generation, socket connection testing.
  - `camera_grid.js` (107 lines) — Multi-camera matrix grid switcher (1x1, 2x2, 3x3), camera focus.
  - `universal_enrollment.js` (292 lines) — Live freeze-frame acquisition, canvas bounding box drag selection, biometrics extraction.
  - `rsac_versions.js` (131 lines) — Descriptor version history retrieval, modal timeline rendering, 1-click rollback.
  - `review_modals.js` (161 lines) — Quick-enroll and candidate reassign modals.
  - `bev_minimap.js` (134 lines) — Tactical 2D top-down minimap canvas, metric grid, projected zone polygons, telemetry entities.
  - `scenario_modals.js` (203 lines) — In-page modal forms for zones, tripwires, homography, and spatial transitions.
  - `journey_search.js` (155 lines) — Trajectory journey queries, timeline rendering, animated MP4 export.
  - `studio_canvas.js` (141 lines) — Studio canvas mouse interaction and vector overlay drawing.
  - `studio_overlays.js` (137 lines) — Overlay toolbar toggles, persistence, scenario lists, and topology transitions rendering.
  - `live_player.js` (121 lines) — Standby poster SVG, stream attach/detach, player HUD buttons, fullscreen handler.
  - `interactive_canvas.js` (205 lines) — Aspect-ratio canvas scaling, bounding box hit testing, tooltip, click-to-tag modal form.
  - `telemetry.js` (178 lines) — WebSocket lifecycle, KPI updates, zone occupancy bars, tripwire tallies, mini-alerts.
  - `gallery_timeline.js` (240 lines) — Entity gallery grid, category filters, sighting timeline queries, snapshot viewer modal.
  - `analytics_view.js` (158 lines) — Chart.js traffic time-series, alerts table, heatmap controls.
  - `backup_manager.js` (54 lines) — System snapshot backup import/restore modal.
- **Decomposed Master Facade Controllers**:
  - `dashboard/static/app.js`: Reduced from 1,263 lines to 345 lines (OK).
  - `dashboard/static/video_scrubber.js`: Reduced from 542 lines to 339 lines (OK).
  - `dashboard/static/studio.js`: Reduced from 994 lines to 328 lines (OK).
  - `dashboard/static/camera_manager.js`: Reduced from 533 lines to 300 lines (OK).
  - `dashboard/static/review_and_rsac.js`: Reduced from 813 lines to 293 lines (OK).
- **HTML Shell & Manifests**:
  - `dashboard/static/index.html`: Added ordered `<script src="/static/js/...">` tags for all 18 submodules ahead of master facade controllers.
  - `.refactor/plan.md` & `dashboard_refactor_plan.md`: Updated Phase 4 to completed status.
  - `.refactor/state.json`: Advanced campaign to COMPLETED (Phase 4 of 4 closed).

### 3. Verification & Modularity Audit
- **Code Health Audit**:
  - Executed `python scripts/code_health_audit.py --path dashboard/static`.
  - Result: **40 files evaluated — 0 Critical, 0 Warning**. Every single CSS and JS file is $\le$ 345 lines (100% compliant with the 350L soft ceiling and 500L hard ceiling).
- **Contract Parity & Invariant Snapshot**:
  - Executed `python scripts/contract_snapshot.py verify --path dashboard --strict`.
  - Result: **OK: Zero contract regressions detected! (DOM IDs, selects, globals, routes, and CSS preserved)**.
- **Contract Smoke Tests**:
  - Executed `python -m unittest tests/test_refactor_contract.py`.
  - Result: **Ran 3 tests in 0.012s — OK (0 failures, 0 errors)**.
- **Dashboard UI Asset Integrity Tests**:
  - Executed `python -m unittest tests/test_dashboard_ui.py`.
  - Result: **Ran 5 tests in 0.370s — OK (0 failures, 0 errors)**.
- **Full Headless Test Suite**:
  - Executed `python -m unittest discover tests` with `MPLBACKEND=Agg`.
  - Result: **Ran 232 tests in 23.603s — OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation Build**:
  - Executed `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`.
  - Result: **Build succeeded with 0 warnings**.

### 4. Refactoring Campaign Summary
Across all 4 phases of the dashboard modernization campaign:
- **Phase 1**: Decoupled `dashboard/stream_manager.py` (880L) into domain services (`services/stream_subscribers.py`, `services/frame_overlay.py`, `services/entity_tagger.py`), maintaining zero-copy NumPy hot path and deep hardware hibernation.
- **Phase 2**: Decoupled `dashboard/app.py` (1,951L) into 8 cohesive APIRouters in `dashboard/routers/` and a thin App Factory with bidirectional dependency injection in `dashboard/dependencies.py`.
- **Phase 3**: Decoupled `dashboard/static/styles.css` (2,902L) into 17 modular ITCSS component stylesheets in `dashboard/static/css/`, completely eliminating all `!important` occurrences.
- **Phase 4**: Decoupled 5 client-side JavaScript monoliths (4,145L total) into 18 focused feature submodules in `dashboard/static/js/`, reducing every single file below 350 lines while preserving 100% contract parity.
- **Final Modularity State**: 0 Critical files, 0 Warning files across the entire `dashboard/` subsystem.


### 5. Post-Refactor Hotfix: Infinite Reload Elimination (Regression Recovery)
- **Root Cause Diagnosis**: `dashboard/static/app.js` contained an accidental assignment `window.location.protocol = window.location.protocol;`. In standard browser specifications, setting `location.protocol` (even to its current value) triggers an immediate full page navigation/reload, causing the dashboard to reload endlessly upon `DOMContentLoaded` (observed as persistent UI flickering and unclickable controls).
- **Scanner Fix**: Updated `_JS_GLOBAL_EXPORT_RE` in `surface_scanners.py` with negative lookahead `\s*=(?!=)` so JavaScript equality comparisons (`===`) are not falsely captured as global symbol assignments.
- **Eliminated Reload Loop**: Removed the dead assignment statement from `dashboard/static/app.js` and cleansed the phantom export from `.refactor/baseline.json`.
- **Automated Regression Guard**: Added explicit assertions in `tests/test_dashboard_ui.py` (`self.assertNotIn("location.protocol =", js)`).
## [Bugfix & UX Modernization] - 2026-10-31 - Accessible Text Truncation, Layout Containment & Interactive Popovers

### 1. Objectives & Scope
- Resolve layout clipping, horizontal overflow, and navigation tab displacement caused by long unconstrained identifiers, video filenames, and stream IDs across the VMS dashboard UI.
- Address empirical bug symptoms:
  1. Video Scrubber card title (`#scrubber-loaded-title`) overflowing `.card-header` and pushing the "+ Add as Active Camera Feed" button out of the card boundary into the adjacent upload column.
  2. Navbar connection status pill (`#connection-status-pill`) ballooning to ~492px, expanding `.header-right` and crushing `.nav-tabs-wrapper` from ~800px down to 338px (displacing tabs and overlapping header buttons).
- Build a reusable, accessible frontend class and utility system (`TextTruncationManager` and `text_truncation.css`) supporting ellipsis (end and smart middle), wrap, and interactive accessible popovers with one-click copy and ESC dismissibility (WCAG 1.4.13 & 4.1.2 compliant).

### 2. Files Modified / Created
- `dashboard/static/css/text_truncation.css` (New, 137 lines):
  - Created base utilities (`.text-truncate`, `.text-ellipsis`, `.text-clamp-2`, `.text-clamp-3`, `.text-wrap-break`).
  - Added layout containment helpers (`.truncate-container`, `.flex-truncate-child`).
  - Designed accessible dark-theme glassmorphic popover (`.truncate-popover`) with viewport collision awareness and copy button.
- `dashboard/static/styles.css`: Added `@import url("css/text_truncation.css");` (0 `!important` rule maintained).
- `dashboard/static/js/text_truncation_manager.js` (New, 236 lines, 8 methods):
  - Encapsulated string truncation strategies (middle truncation preserving file extensions, end ellipsis, wrap).
  - Built WCAG 1.4.13-compliant interactive popover (`role="tooltip"`, `aria-describedby`, hover/focus trigger, hoverable popover body, ESC key dismissal, one-click clipboard copy with animated feedback).
- `dashboard/static/index.html`:
  - Added `<script src="/static/js/text_truncation_manager.js"></script>` ahead of dependent modules.
  - Added `.text-truncate` class and title fallback to `#scrubber-loaded-title`.
- `dashboard/static/css/scrubber.css`:
  - Added defensive layout containment (`min-width: 0`, `flex: 1 1 auto`) to `.video-player-card .card-header`, `#scrubber-loaded-title`, and `.video-file-meta`.
- `dashboard/static/css/layout.css`:
  - Added `flex-shrink: 0; min-width: 0;` to `.header-right`.
  - Added `max-width: 260px; min-width: 0;` to `.connection-status-pill` and `min-width: 0; text-overflow: ellipsis;` to `#connection-status-text`.
- `dashboard/static/video_scrubber.js`:
  - Applied `window.TextTruncationManager.apply` on `#scrubber-loaded-title` with middle truncation and accessible popover.
- `dashboard/static/app.js`:
  - Applied `window.TextTruncationManager.apply` on `#connection-status-text` when stream ID exceeds 14 chars.
- `dashboard/static/js/video_library.js`:
  - Integrated `TextTruncationManager.format` and `.truncate-trigger` for recording list file cards.
- `tests/test_dashboard_ui.py`:
  - Added automated static asset integrity assertions for `.text-truncate`, `.truncate-popover`, and `TextTruncationManager`.

### 3. Verification & Empirical Proof
- **Contract & AST Surface Invariants**:
  - `python -m unittest tests/test_refactor_contract.py`: **3 tests in 0.012s — OK (0 `!important` occurrences, all DOM IDs preserved)**.
- **Unit & UI Integration Tests**:
  - `python -m unittest tests/test_dashboard_ui.py`: **5 tests in 0.361s — OK**.
  - `python -m unittest discover tests`: **232 tests in 24.239s — OK (100% green)**.
- **Container Synchronization**:
  - Ran `run_diagnose.py container --sync-check`: Verified 100% in sync with Docker runtime container.
- **Live Chrome CDP Empirical Layout Verification**:
  - Scrubber Card Header (`#scrubber-loaded-title`):
    - Before: `titleWidth = 717.56px`, `cardHeaderScrollWidth = 1093px > cardHeaderWidth = 998px` (95px overflow, displacing action buttons).
    - After: `titleFormattedText = 'Loaded: 20260912...50d9e_G94106186.mp4'`, `cardHeaderWidth = 998px`, `cardHeaderScrollWidth = 998px` (`hasHeaderOverflow = false`). Button right edge at 874px safely inside card boundary (1056px).
  - Navbar Connection Pill (`#connection-status-pill`):
    - Before: `connPillWidth = 491.98px`, `headerRightWidth = 787.88px`, `navTabsWidth = 338.31px` (navigation tabs crushed, buttons displaced/wrapped).
    - After: `connText = 'Connected (...G94106186)'`, `connPillWidth = 187.92px` (reduced by 304px), `headerRightWidth = 578.94px`, `navTabsWidth = 547.25px` (tabs restored with +209px breathing room).
  - Popover Interaction:
    - Hover/focus over truncated elements triggers top-layer `#text-truncation-popover` (`role="tooltip"`, `aria-describedby`).
    - ESC key, mouseleave, or clicking outside cleanly dismisses the popover.
    - One-click "Copy" button successfully writes the full string to clipboard with "Copied!" visual confirmation.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: **Build succeeded with 0 warnings**.
## [Bugfix & Architecture Hardening] - 2026-11-01 - Sturdy Camera Device Handler & USB Stream Acquisition

### 1. Objectives & Scope
- Resolve USB camera feed failures when running `main.py --source real` (`0` frames processed, pipeline timeout).
- Resolve USB device detection failures when using "Scan for Devices" in the web dashboard.
- Eliminate camera driver locking, COM apartment collisions, and device blocking during rapid open/close sequences on Windows.
- Implement a sturdy, centralized hardware camera abstraction (`CameraDeviceHandler`) adhering strictly to Modularity Budgets (target 150-300 lines, SRP).

### 2. Files Modified / Created
- `intelligent_tracker/camera_device.py` (New, 228 lines):
  - Created centralized `CameraDeviceHandler` class with cross-platform backend fallback (`DirectShow` -> `Media Foundation` -> `V4L2` -> `AVFoundation`).
  - Thread-safe acquisition mutex (`_device_lock`) preventing race conditions and concurrent DirectShow COM graph collisions.
  - Driver unbind settle cooldown protocol (`safe_release(cap, settle_delay=0.25)`).
  - Robust visual frame validation (`validate_frame(frame, min_std=0.5)`).
  - Clean device probing (`probe_device(idx)`), discovery (`discover_usb_cameras()`), and first-working selection (`find_first_working_camera()`).
  - Container environment awareness (`is_container_environment()`).
- `intelligent_tracker/video.py` (Reduced by 34 lines):
  - Modernized `is_physical_camera()` to validate active frames rather than relying on brittle hardware register properties (`CAP_PROP_BRIGHTNESS` etc. which return `-1.0` on modern UVC devices).
  - Delegated `find_physical_cameras()` and `find_first_real_camera()` to `CameraDeviceHandler`.
  - Routed `VideoSource._open_capture()` through `CameraDeviceHandler.open_camera()` and `safe_release()`.
- `intelligent_tracker/discovery.py` (Reduced by 14 lines):
  - Updated `find_physical_cameras()` to return detected USB devices with resolution, FPS, and backend metadata from `CameraDeviceHandler`.
  - Updated `test_camera_connection()` to safely acquire, test, and release video captures via `CameraDeviceHandler`.
  - Added Docker container notice clarifying that host USB webcams are isolated by default in containers.
- `dashboard/static/js/camera_discovery.js`:
  - Updated empty-state discovery message to clarify Docker container isolation vs host execution.
- `tests/test_camera_device.py` (New, 140 lines):
  - 13 comprehensive unit tests covering frame validation, safe release, backend hierarchy, mock probing, sequential discovery, and source resolution.

### 3. Verification & Empirical Proof
- **Symptom 1 Reproduction & Resolution**:
  - *Before*: `python main.py --detector yolov8 --classes person --conf 0.40 --source real` resulted in `Processed Frames: 0`, `[WARN] Video source timeout or stream completed.`
  - *After*: `python main.py --detector yolov8 --classes person --conf 0.40 --source real --frames 10 --headless` auto-detects real camera, ingests frames at ~29 FPS with `Processed Frames: 10`, 0 reconnects, and 0 timeouts.
- **Symptom 2 Device Discovery & Probing**:
  - `discover_all_cameras(include_usb=True)` successfully discovers connected USB cameras (e.g. `USB Camera 0` @ 640x480, `USB Camera 1` @ 1920x1080).
  - Back-to-back testing of sources `0` and `1` succeeds with 100% reliability (`Res 0: True 640x480`, `Res 1: True 1920x1080`) with zero COM unbind collisions.
- **Automated Test Suite**:
  - `python -m unittest tests/test_camera_device.py`: **13 tests in 0.832s — OK**.
  - `python -m unittest discover -s tests -p "test_*.py"`: **245 tests in 40.177s — OK (100% green)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: **Build succeeded with 0 warnings**.
## [Bugfix & Architectural Resilience] - 2026-11-01 - Heterogeneous Re-ID Embedding Dimension Alignment & Defensive Guard

### 1. Objectives & Scope
- Resolve runtime exception `ValueError: shapes (1,2560) and (384,) not aligned: 2560 (dim 1) != 384 (dim 0)` during `main.py` pipeline execution when matching enrolled entity signatures.
- Support heterogeneous feature extractors (`DualModelFeatureExtractor` [2560-d], `OnnxReIDExtractor` [512-d], `ColorHistogramExtractor` [384-d], `MockFeatureExtractor` [16-d]) coexisting in SQLite database without crashing matrix math operations.
- Establish a multi-tier defense architecture:
  - **Tier 1 (Database / Query Level)**: Parameterized dimension filtering in `TrackerDB.get_gallery_embeddings(expected_dim=...)`.
  - **Tier 2 (Matcher Level)**: Automatic `expected_dim` injection from active extractor with descriptive dimension mismatch notifications in `GalleryMatcher.reload_gallery()`.
  - **Tier 3 (Math Primitive Level)**: Defensive vector alignment validation in `batch_cosine_similarity()`.
  - **Tier 4 (CLI Orchestration)**: Automatic extractor detection in `main.py` for enrolled galleries and support for `--reid dual` / `--reid dual_model`.

### 2. Files Modified / Created
- `intelligent_tracker/reid.py`:
  - Added dimension alignment guard in `batch_cosine_similarity()`: returns empty score array and logs warning if `gallery.shape[1] != q.shape[0]`.
  - Added `embedding_dim` property to `BaseFeatureExtractor`.
- `intelligent_tracker/database.py`:
  - Enhanced `TrackerDB.get_gallery_embeddings(expected_dim=None)` to safely filter deserialized BLOB embeddings by dimension, preventing `np.vstack` dimension collision crashes.
- `intelligent_tracker/matcher.py`:
  - In `GalleryMatcher.reload_gallery()`, pass `expected_dim=getattr(self.extractor, "embedding_dim", None)` to query only compatible signatures.
  - Added informative logging when database signatures are skipped due to dimension incompatibility, directing users to the matching `--reid` engine.
- `main.py`:
  - Added `"dual"` and `"dual_model"` to `--reid` argument choices.
  - Added intelligent extractor auto-detection: when `--reid` is not specified, probes `tracker.db` signature dimension and automatically selects `"dual"` (2560-d) or `"onnx"` (512-d).
- `tests/test_reid.py`:
  - Added `test_batch_cosine_similarity_dimension_mismatch` verifying graceful empty array return on misaligned dimensions.
- `tests/test_matcher.py`:
  - Added `test_dimension_mismatch_filtering` verifying SQLite signatures with incompatible dimensions are ignored without crashing.

### 3. Verification & Empirical Proof
- **Symptom Reproduction & Resolution**:
  - *Before*: `python main.py --detector yolov8 --classes person --conf 0.40 --source real` crashed with `ValueError: shapes (1,2560) and (384,) not aligned: 2560 (dim 1) != 384 (dim 0)`.
  - *After*:
    - Default auto-detection: `python main.py --detector yolov8 --classes person --conf 0.40 --source real --frames 10 --headless` auto-selects `dual` Re-ID engine, connects to webcam #0, recognizes 1 enrolled signature, and processes all 10 frames smoothly.
    - Explicit override: `python main.py --detector yolov8 --classes person --conf 0.40 --source real --reid color --frames 5 --headless` filters incompatible signatures (gallery: 0 signatures) and processes frames without error.
- **Automated Test Suite**:
  - `python -m unittest tests/test_reid.py tests/test_matcher.py`: **15 tests in 0.154s — OK**.
  - `python -m unittest discover tests`: **247 tests in 32.186s — OK (100% green)**.
## [Feature & Diagnostics] - 2026-11-01 - Friendly Camera Discovery, Multi-Consumer Proxy & Device Resource Manager

### 1. Objectives & Scope
- Resolve hardware device locking collisions where multiple processes or streams competing for the same physical camera cause `Could not open video capture device or RTSP stream`.
- Enumerate real, human-readable friendly camera hardware names (`GoPro Webcam`, `OBS Virtual Camera`) via Windows DirectShow registry (`winreg`) and Linux v4l2 rather than opaque `USB Camera {index}` labels.
- Differentiate and prioritize real physical hardware cameras over virtual loopback devices (e.g. `OBS Virtual Camera`, `DroidCam`) when resolving `--source real`.
- Provide a dedicated Camera Resource Manager CLI (`scripts/camera_manager.py`) to inspect device status (`AVAILABLE`, `BUSY / LOCKED`, `NOT PRESENT`), identify locking processes (PIDs), and execute safe unbind driver resets.
- Add shared stream awareness to the web VMS test endpoint (`/api/cameras/test`) so testing an already-streaming channel grabs the live frame buffer without triggering hardware exclusive lock conflicts.
- Add Web UI "Release Blocked" trigger and multi-consumer proxy documentation for Docker (`host.docker.internal`).

### 2. Files Modified / Created
- `intelligent_tracker/camera_device.py`:
  - Added `get_device_names()` and `get_friendly_name(index)` utilizing zero-dependency native Windows Registry `winreg` and Linux `/sys/class/video4linux`.
  - Added `is_virtual_device(name)` to classify virtual loopback feeds.
  - Enhanced `find_first_working_camera(prefer_physical=True)` to prioritize physical webcams over virtual cameras.
  - Added `resolve_source()` with friendly name substring resolution (e.g. `'gopro'` -> index 1).
- `intelligent_tracker/camera_tool.py` (New):
  - Created standalone diagnostic & resource management utility supporting `--status`, `--release`, `--kill-orphans`, and `--test <idx>`.
- `scripts/camera_manager.py` (New):
  - Created root CLI shortcut script.
- `intelligent_tracker/discovery.py`:
  - Enriched `find_physical_cameras()` with friendly device names and virtual badges.
  - Enhanced `test_camera_connection()` to return specific, actionable diagnostics when a detected device is busy/locked by another application.
- `dashboard/routers/cameras.py`:
  - Added `CameraPool` active stream lookup in `test_camera_connection_route()`: returns live frame buffer if the camera is already running in VMS.
  - Added `POST /api/cameras/release` endpoint to trigger driver cooldown.
- `dashboard/static/index.html` & `dashboard/static/js/camera_discovery.js` & `dashboard/static/camera_manager.js`:
  - Added "Release Blocked" button (`#btn-release-cameras`).
  - Added virtual badge indicators and FPS metadata in discovery cards.
- `tests/test_camera_tool.py` (New):
  - 7 unit tests covering name resolution, virtual classification, source resolution, and resource inspection.

### 3. Verification & Empirical Proof
- **Diagnostic Inspection**:
  - `python scripts/camera_manager.py --status` accurately maps Device #0 to `OBS Virtual Camera` (Virtual, 640x480) and Device #1 to `GoPro Webcam` (Hardware, 1920x1080).
- **Physical Prioritization**:
  - `python main.py --source real --frames 5 --headless` auto-selects `GoPro Webcam` (Hardware device index #1) over `OBS Virtual Camera`.
- **Friendly Name CLI Resolution**:
  - `python main.py --source gopro` successfully resolves to index #1 (`GoPro Webcam`).
- **Automated Test Suite**:
  - `python -m unittest tests/test_camera_tool.py`: **7 tests in 9.732s — OK**.
  - `python -m unittest tests/test_camera_device.py`: **13 tests in 1.023s — OK**.
  - `python -m unittest discover tests`: **254 tests in 41.980s — OK (100% green)**.
## [Enhancement & Docs] - 2026-11-01 - Targeted Camera/PID Release, Self-Process Exclusion & Sphinx/README Documentation

### 1. Objectives & Scope
- Provide targeted release for a specific camera index (`--release-camera <INDEX>` / `--free <INDEX>`) and targeted process termination (`--kill-pid <PID> [--force]`) in `camera_tool.py` and `scripts/camera_manager.py`.
- Filter out the running `camera_manager.py` / `camera_tool.py` command itself from the active worker process list in inspection reports.
- Author dedicated Sphinx documentation (`documentation/camera_management.rst`) covering DirectShow / V4L2 exclusive locking, friendly device aliases, CLI tooling, and the multi-consumer stream proxy pattern.
- Update `documentation/index.rst`, `README.rst`, `documentation/analytics.rst`, and `documentation/detectors.rst` with valid RST tables and OS-agnostic runnable commands.
- Ensure 100% green Sphinx build (`sphinx -E -W --keep-going`) with 0 warnings.
- Verify full test suite (256 tests, 100% green).

### 2. Files Modified / Created
- `intelligent_tracker/camera_tool.py`:
  - Added `terminate_process_by_pid(pid: int, force: bool = False) -> bool` with graceful SIGTERM and immediate SIGKILL fallbacks.
  - Added `release_camera_by_index(index: int, force: bool = False) -> Dict[str, Any]` for targeted device cooldown.
  - Enhanced `find_camera_worker_processes()` to filter out the caller script PID, parent PID, and processes running `camera_manager` or `camera_tool`.
  - Added CLI flags: `--release-camera <INDEX>`, `--kill-pid <PID> [PID...]`, `--force` (`-f`).
- `scripts/camera_manager.py`:
  - Added CLI forwarding for `--release-camera` and `--kill-pid`.
- `tests/test_camera_tool.py`:
  - Added unit tests: `test_terminate_process_by_pid_not_found`, `test_release_camera_by_index`.
- `documentation/camera_management.rst` (New):
  - Comprehensive guide covering OS capture subsystems, exclusive hardware locks, friendly names, CLI management, multi-consumer shared proxy, and scenario matrix.
- `documentation/index.rst`:
  - Added `camera_management` under the Dashboard, VMS & Spatial Studio toctree.
- `README.rst`:
  - Added "Hardware Camera Management & Exclusive Lock Recovery" and "Multi-Consumer Shared Stream Proxy" sections.
  - Expanded Scenario Combinations Matrix with audit, release, kill, friendly source, and stream proxy commands.
  - Sanitized commands to OS-agnostic standard syntax (`python ...`).
- `documentation/analytics.rst` & `documentation/detectors.rst`:
  - Fixed table borders and docutils list indentation formatting to achieve 0 Sphinx warnings.

### 3. Verification & Empirical Proof
- **Targeted Camera Release & Kill PID**:
  - `python scripts/camera_manager.py --release-camera 2` cleanly reports status, device name, and pin cooldown.
  - `python scripts/camera_manager.py --kill-pid 999999` safely handles non-existent PIDs without crash.
- **Self-Process Exclusion**:
  - `python scripts/camera_manager.py --status` reports other workers without listing itself as an active camera process.
- **Sphinx Documentation Clean Build**:
  - `python -m sphinx -E -W --keep-going documentation/ documentation/_build/html/`: **build succeeded with 0 warnings**.
- **Automated Test Suite**:
  - `python -m unittest discover tests`: **Ran 256 tests in 46.759s — OK (100% green)**.

---
## [Milestone 11] - 2026-11-02 - Responsive Navigation & Zero-Overflow Layout Encapsulation

### 1. Objectives & Scope
- Resolve layout clipping, navigation inconsistencies, and responsiveness defects across all 9 dashboard tabs in `dashboard/static/index.html`.
- Guarantee baseline support down to 320px minimum viewport width (360px standard mobile) and 256px minimum viewport height.
- Eliminate coexistence conflict where `#btn-mobile-menu` (hamburger) and `.nav-tabs-container` (containing `#btn-quick-tabs` and scroll arrows) appeared simultaneously on mobile / portrait tablet breakpoints ($\le 1024$px).
- Provide modern, cyber-styled glassmorphic theme for `#btn-quick-tabs` (Jump button) with gradient fill, cyan border accent, clear icon/label hierarchy, and 34px vertical alignment.
- Fix horizontal scroll arrow mechanics (`#nav-tabs-prev`, `#nav-tabs-next`) by replacing offsetParent-dependent coordinate logic with viewport-relative `getBoundingClientRect()` edge detection and native CSS scroll-snap integration.
- Ensure all 9 dashboard tabs fit cleanly within each breakpoint without uncontained horizontal document scrolling (`scrollWidth <= innerWidth`).
- Add comprehensive automated unit and integration tests (`tests/test_responsive_navigation.py`) enforcing structural HTML integrity, static delivery, mobile-first coexistence rules, touch target dimensions, and zero `!important` compliance.

### 2. Files Modified / Created
- `dashboard/static/css/responsive_patterns.css` (New, 328 lines):
  - Encapsulated reusable responsive patterns: mobile-first `.nav-tabs-container` (`display: none` by default; `display: flex` at $\ge 1025$px).
  - Styled `.nav-quick-select-btn` (Jump button), `.nav-quick-dropdown`, and `.nav-scroll-btn` (`prev` / `next`).
  - Desktop-small compacting at $\le 1280$px: `.btn-text { display: none; }` inside header action buttons, hiding `.live-pill`.
  - Reusable layout containment for `.glass-panel`, `.card-header`, `.card-actions`, `.chart-wrapper`, `canvas#trafficChart`, and `.table-responsive`.
  - Strictly 0 `!important` declarations, adhering to quantitative modularity ceiling ($\le 350$ lines).
- `dashboard/static/js/nav_tabs_manager.js` (New, 258 lines):
  - Reusable navigation tabs and quick jump manager class (`NavTabsManager`).
  - `scrollNext()` and `scrollPrev()` using `getBoundingClientRect()` for coordinate-independent tab boundary detection.
  - Dynamic button disabling (`prevBtn.disabled`, `nextBtn.disabled`) based on scroll offset.
  - Dropdown menu with active tab indicators and automatic keyboard navigation (`Escape`, `ArrowLeft`, `ArrowRight`, `Home`, `End`).
- `dashboard/static/index.html`:
  - Structured `.nav-tabs-container` featuring `#nav-tabs-prev`, `#nav-tabs-next`, `#btn-quick-tabs`, and `#nav-quick-dropdown`.
  - Wrapped header button labels in `<span class="btn-text">` for clean icon-only collapsing at $\le 1280$px.
  - Linked `responsive_patterns.css` and loaded `nav_tabs_manager.js`.
- `dashboard/static/styles.css`:
  - Imported `css/responsive_patterns.css`.
- `dashboard/static/css/responsive.css`:
  - Refined breakpoint queries at 1280px, 1080px, 1024px, 768px, 580px, 360px, 320px.
- `tests/test_responsive_navigation.py` (New, 160 lines):
  - 6 unit/integration tests verifying tab presence, header controls, responsive static delivery, CSS zero `!important` linting, mobile-first partition contract, and JS `getBoundingClientRect` scrolling engine.

### 3. Verification & Empirical Proof
- **Headless Chrome CDP Multi-Breakpoint Inspection (1440, 1280, 1200, 1065, 1024, 768, 580, 360, 320px)**:
  - $\ge 1025$px: Hamburger hidden, desktop tab container visible, jump button visible, document overflow = 0.
  - $\le 1024$px: Hamburger visible, desktop tab container hidden, zero coexistence conflict, document overflow = 0.
- **Scroll Arrow & Jump Button Empirical Diagnostics**:
  - Initial `scrollLeft`: 13.
  - After `#nav-tabs-next` click: `scrollLeft`: 305 (smooth animation, `prevBtn` enabled).
  - After `#nav-tabs-prev` click: `scrollLeft`: 158 (smooth backward animation).
  - Jump button click: Opens dropdown with 9 items; selecting tab switches pane and closes dropdown.
- **Sphinx Documentation Clean Build**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: **build succeeded with 0 warnings**.
- **Automated Test Suite**:
  - `python -m unittest discover tests`: **Ran 262 tests in 54.164s — OK (100% green, 0 failures, 0 errors)**.


---
## 2026-11-02: Fix Nav Scroll Prev Button Disabled State, Header Gaps & Layout Design Standards Enforcement

### 1. Root Cause Breakdown
- **Symptom 1 (`#nav-tabs-prev` not disabling at start)**:
  - In `dashboard/static/js/nav_tabs_manager.js`, `updateScrollButtons()` checked `this.prevBtn.disabled = scrollLeft <= 4;`.
  - However, CSS scroll-snap (`scroll-snap-type: x mandatory` with `.nav-tab { scroll-snap-align: start }`) combined with `.nav-tabs-wrapper` (8px padding) and `.nav-tabs` (4px padding + 1px border) establishes the resting `offsetLeft` of the first tab at 13px. When scrolled to the start, `scrollLeft` rests at 13px ($13 > 4$), so the button remained enabled indefinitely.
  - **Fix**: Added snap-aware `isAtStart()` and `isAtEnd()` methods that inspect the first and last tab bounding client rects against the wrapper container (`firstRect.left >= wrapRect.left - 4 || scrollLeft <= (firstTab.offsetLeft + 2)`), and ensure `scrollPrev()` explicitly smooth-scrolls to 0 when near the start boundary.
- **Symptom 2 (Right scroll button sticking flush against `.header-right`)**:
  - In `dashboard/static/css/layout.css`, `.app-header` had default `gap: normal` (0px) and `.nav-tabs-container` had `margin: 0`, causing `#nav-tabs-next` to sit flush against the first button in `.header-right`.
  - **Fix**: Added `gap: 16px;` to `.app-header` and `margin: 0 8px; gap: 8px;` to `.nav-tabs-container` in `dashboard/static/css/responsive_patterns.css`, ensuring a clean, symmetric 24px visual separation without layout collision.
- **Rule Enforcement**:
  - Enshrined Spacing & Separation Discipline, Zero Collision & Overlap Guarantee, Strict Viewport Containment, and Resilient Directional Control States into `AGENTS.md` and global rules (`security_and_standards.md`, `modernization_rules.md`).
  - Added unit regression tests in `tests/test_responsive_navigation.py` asserting header spacing, margin isolation, and snap offset compensation contracts.

### 2. Files Modified
- `dashboard/static/js/nav_tabs_manager.js`:
  - Added `isAtStart()` and `isAtEnd()`; updated `scrollPrev()` and `switchTab()` with boundary clamping and delayed button refresh.
- `dashboard/static/app.js`:
  - Added `Math.max(0, targetLeft)` clamping and synchronized `window.navTabsManager.updateScrollButtons()`.
- `dashboard/static/css/layout.css`:
  - Added `gap: 16px;` to `.app-header`.
- `dashboard/static/css/responsive_patterns.css`:
  - Added `margin: 0 8px; gap: 8px;` to desktop `.nav-tabs-container`.
- `tests/test_responsive_navigation.py`:
  - Added `test_header_spacing_and_gap_discipline` and `test_nav_tabs_manager_snap_offset_and_disable_contracts`.
- `AGENTS.md`:
  - Formalized Frontend Spacing & Structural Separation, Zero Overlap, and Viewport Containment standards.

### 3. Verification & Empirical Proof
- Automated unit tests: `python -m unittest tests/test_responsive_navigation.py` -> 9/9 tests passed (0 failures, 0 errors).
- Full test suite: `python -m unittest discover -s tests -p "test_*.py"` -> Ran 265 tests in 49.224s — OK (100% green).

---
## 2026-11-02: Environment-Agnostic Camera Storage, Hybrid Device Signature Resolution & Diagnostics Error UI

### 1. Objectives & Scope
- **Environment-Agnostic Path Normalization**:
  - Implemented bidirectional normalization between Docker container paths (`/app/data/videos/...`) and host paths (`data/videos/...`).
  - Added multi-root candidate fallback resolution in `CameraPathResolver.resolve_file_source()`, probing direct paths, workspace-relative roots, and `data/videos/` base filenames.
- **Hybrid Device Signature & Virtual Camera Safety**:
  - Implemented friendly device name binding (e.g. `device_name: "GoPro Webcam"` or `"USB Camera 2"`) in `CameraPathResolver.resolve_camera_source()`, dynamically re-mapping shifted DirectShow hardware indices on Windows across reboots and reconnections.
  - Hardened `--source real` / `auto` auto-detection to strictly exclude virtual loopback devices (e.g. OBS Virtual Camera), preventing virtual cameras from taking over physical feeds.
  - Fixed `scripts/camera_manager.py --status` and `intelligent_tracker/camera_tool.py` to report inactive virtual cameras as `IDLE (OFFLINE)` rather than falsely marking them as `BUSY (LOCKED)`.
- **Camera Health Manager & Diagnostic Traceback Engine**:
  - Delivered `CameraHealthManager` (`dashboard/services/camera_diagnostics.py`) providing structured error tracking (`CameraHealthReport`), traceback capture, and actionable remediation suggestions.
  - Replaced the perpetual, silent `"Camera Initializing..."` hanging state in `StreamManager._worker_loop` with dynamic error placeholder frame synthesis displaying `[!] FILE_NOT_FOUND`, `[!] DEVICE_LOCKED`, or `[!] RTSP_TIMEOUT` alongside error codes and remediation advice.
- **Diagnostics API & Frontend UI Inspector**:
  - Created `dashboard/routers/camera_diagnostics.py` exposing `GET /api/cameras/{id}/diagnostics`, `POST /api/cameras/{id}/release`, `POST /api/cameras/{id}/probe`, and `GET /api/cameras/diagnostics/summary`.
  - Created `dashboard/static/css/camera_diagnostics.css` with responsive, zero-`!important` glassmorphism styles.
  - Created `dashboard/static/js/camera_diagnostics_ui.js` providing error banner overlays, a modal dialog (`#modal-camera-diagnostics`) with full tracebacks, and a direct "Edit in Camera Manager" bridge.
  - Enhanced `dashboard/static/camera_manager.js` to support inline "✏️ Edit" actions, form pre-population, `device_name` capture during device scans, and `PUT /api/cameras/{id}` updates without stream interruptions.

### 2. Files Modified & Created
- `intelligent_tracker/camera_resolver.py`: Created core environment-agnostic path and device resolver.
- `dashboard/services/camera_resolver.py`: Re-export facade maintaining clean architectural boundaries.
- `dashboard/services/camera_diagnostics.py`: Created `CameraHealthManager` singleton and error placeholder renderer.
- `dashboard/routers/camera_diagnostics.py`: Created REST API endpoints for telemetry, release, and probing.
- `dashboard/routers/__init__.py`: Registered and re-exported `camera_diagnostics_router`.
- `dashboard/app.py`: Mounted `camera_diagnostics_router`.
- `dashboard/camera_pool.py`: Integrated `CameraPathResolver` and `CameraHealthManager`, added `device_name` support and diagnostic fields to `list_cameras()`.
- `dashboard/stream_manager.py`: Added consecutive failure detection, health status tracking, and error frame rendering in `_worker_loop`.
- `intelligent_tracker/camera_tool.py`: Fixed `is_virt` status reporting to `IDLE (OFFLINE)`.
- `intelligent_tracker/video.py`: Replaced naive fallback to index 0 with safe physical registry resolution.
- `dashboard/static/css/camera_diagnostics.css`: Created scoped styles for error badges, banners, and diagnostic modal.
- `dashboard/static/js/camera_diagnostics_ui.js`: Created UI module for banners, diagnostic modal, and traceback inspector.
- `dashboard/static/camera_manager.js`: Added "✏️ Edit" action, form population, `PUT` updates, and `device_name` storage.
- `dashboard/static/index.html`: Linked diagnostic CSS/JS and injected `#modal-camera-diagnostics`.
- `tests/test_camera_resolver.py`: Added 5 unit tests for path normalization, device name re-mapping, and virtual camera rejection.
- `tests/test_camera_diagnostics.py`: Added 4 unit tests for health state transitions, error frame generation, and API endpoints.

### 3. Verification & Empirical Proof
- **Contract & Architecture Tests**:
  - `python -m unittest tests/test_refactor_contract.py`: 3/3 tests passed (HTML element IDs preserved, zero `!important` in CSS).
- **Resolver & Diagnostics Tests**:
  - `python -m unittest tests/test_camera_resolver.py`: 5/5 tests passed (0 failures, 0 errors).
  - `python -m unittest tests/test_camera_diagnostics.py`: 4/4 tests passed (0 failures, 0 errors).
- **Camera Device & Tool Verification**:
  - `python scripts/camera_manager.py --status`: Correctly reports `#0 OBS Virtual Camera` as `IDLE (OFFLINE)` and physical cameras as `AVAILABLE`.
  - `python main.py --source real`: Correctly resolves to physical GoPro Webcam (`#1`), strictly rejecting the virtual loopback device.
- **Full Repository Test Suite**:
  - `python -m unittest discover tests`: Ran 274 tests in 69.505s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation Clean Build**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: **build succeeded with 0 warnings**.


---
## 2026-11-02: App Debugger - Resolution of Uvicorn Graceful Shutdown Deadlock & Windows DirectShow COM ActiveMovie Zombie Process

### 1. Symptoms & Incident Triage
- User ran Uvicorn server: `python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000` (without `--reload`).
- When sending `CTRL + C` (SIGINT), the console printed:
  ```
  INFO:     Shutting down
  INFO:     Waiting for connections to close. (CTRL+C to force quit)
  ```
- User closed the browser tab at `$APP_URL/#live`, but the shutdown remained hung.
- Pressing `CTRL + C` a second time failed to exit or respond.
- Status inspection revealed orphaned worker processes:
  `- PID 55908 | [TRACKER/DASHBOARD] | 164.6 MB | python.exe` (with window title: `ActiveMovie Window`, consuming 2h26m CPU).

### 2. Root Cause Analysis
1. **Uvicorn Infinite StreamingResponse Deadlock**:
   - `dashboard/routers/streaming.py` served an infinite generator `frame_generator()` inside `StreamingResponse`.
   - When Uvicorn received SIGINT, `H11Protocol.shutdown()` marked `keep_alive = False` but left transport open awaiting response completion.
   - Uvicorn entered `while self.server_state.connections and not self.force_exit: await asyncio.sleep(0.1)` with default `timeout_graceful_shutdown = None` (infinite).
   - Because `frame_generator()` only checked `request.is_disconnected()` (a client-driven check), the connection was never closed from the server side.
2. **DirectShow COM Filter Graph Teardown Deadlock**:
   - In `intelligent_tracker/video.py`, `VideoSource.stop()` relied on `_capture_worker` to release `self._cap` inside its `finally:` block.
   - When `self._thread.join(timeout=2.0)` timed out (due to hardware read/reconnect or DirectShow C++ COM block), `VideoSource.stop()` abandoned `self._cap` without releasing it.
   - On Windows, OpenCV's DirectShow backend (`cv2.CAP_DSHOW`) creates an internal Win32 message window (`ActiveMovie Window`).
   - When Python's main thread initiated runtime finalization (`Py_FinalizeEx`), Windows loader lock and the active DirectShow COM STA thread deadlocked with the CRT exit routines, creating a permanent zombie process ignoring signals.
3. **Class-Level Lock Guarding**:
   - `CameraDeviceHandler.safe_release()` acquired `_device_lock` without a timeout, leading to thread contention during concurrent device teardown.

### 3. Surgical Code Fixes
- **`dashboard/dependencies.py`**:
  - Implemented thread-safe and loop-safe `get_shutdown_event()`, `is_shutting_down()`, and `set_shutting_down(bool)`.
- **`dashboard/app.py`**:
  - In `lifespan()`, immediately called `set_shutting_down(True)` upon shutdown initiation before stopping stream managers and pools.
- **`dashboard/routers/streaming.py`**:
  - Bound `shutdown_evt = get_shutdown_event()` inside `frame_generator()`. Replaced blocking sleeps with `await asyncio.wait_for(shutdown_evt.wait(), timeout=0.04)`, guaranteeing instantaneous (<1ms) generator exit when shutdown starts.
  - In `websocket_telemetry_endpoint`, added a `shutdown_task` to `asyncio.wait()`, ensuring clean disconnection and task cancellation on server stop.
- **`intelligent_tracker/video.py`**:
  - In `VideoSource.stop()`, injected a sentinel `None` into `self._queue` to unblock any thread awaiting `read()`.
  - Added an explicit hardware capture release block inside `VideoSource.stop()`, guaranteeing that `CameraDeviceHandler.safe_release(self._cap)` is executed even if the worker thread join times out.
  - In `VideoSource.read()`, safely handled sentinel values when `self._running` is `False`.
- **`intelligent_tracker/camera_device.py`**:
  - Guarded `safe_release()` device lock acquisition with `cls._device_lock.acquire(timeout=2.0)`, ensuring release operations cannot hang on a deadlocked mutex.
- **Process Cleanup**:
  - Force-terminated zombie processes PID 55908 and PID 37644 via `camera_manager.py --kill-pid 55908 --force`.
  - Re-verified hardware readiness via `camera_manager.py --status`: all cameras (`#0 OBS`, `#1 GoPro`, `#2 USB Camera 2`) freed and returned to `AVAILABLE`.
- **`.TODO/Commands`**:
  - Added `--timeout-graceful-shutdown 3` to Uvicorn command recipes to enforce a strict hard-cap on connection drainage.

### 4. Verification & Testing
- **New Unit Regression Test**:
  - Added `test_11_streaming_shutdown_termination` to `tests/test_dashboard.py` verifying state transitions and loop-safe shutdown event handling.
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 275 tests in 43.353s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## 2026-11-02: Frontier Architect - SSOT Camera Resolver Consolidation & Zombie Facade Elimination

### 1. Objectives & Scope
- Resolve dual-maintenance anti-pattern identified in architectural audit of commit `f2a7d87a`.
- Purge unreferenced zombie facade `dashboard/services/camera_resolver.py`.
- Consolidate camera resolution logic on Single Source of Truth (SSOT) by refactoring `CameraDeviceHandler.resolve_source()` to delegate directly to `CameraPathResolver.resolve_camera_source()`.
- Eliminate divergence risk ensuring all legacy and script callers benefit from virtual OBS camera rejection, Docker-to-host path normalization, and dynamic friendly name re-mapping.

### 2. Files Touched
- `dashboard/services/camera_resolver.py`:
  - **Deleted**: Purged 11-line zombie re-export shim with zero consumers.
- `intelligent_tracker/camera_device.py`:
  - Refactored `CameraDeviceHandler.resolve_source()` to a 1-line delegation pass-through calling `CameraPathResolver.resolve_camera_source()`.
  - Preserved full backwards compatibility while extending optional `device_name` and `prefer_physical` parameters.
  - Reduced file size from 342 lines to 300 lines (comfortably within the 150–300 lines healthy modularity target).
- `tests/test_camera_tool.py`:
  - Added `test_resolve_source_delegation_ssot_virtual_rejection` verifying virtual loopback device rejection via SSOT.
  - Added `test_resolve_source_dynamic_device_name_remap` verifying dynamic index shift re-mapping.

### 3. Verification & Testing
- **Subsystem Unit Tests**:
  - `python -m unittest tests/test_camera_tool.py tests/test_camera_resolver.py`: 16/16 tests passed — **OK (0 failures, 0 errors)**.
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 277 tests in 49.248s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## 2026-11-02: Complete Decrufting & Total Elimination of `__future__` Imports

### 1. Objectives & Scope
- Modernize all Python modules to native Python 3.10–3.12+ syntax by removing all remaining `from __future__ import annotations` (PEP 563) statements.
- Eliminate runtime reflection overhead in FastAPI routers (`dashboard/routers/`) and Pydantic schemas (`dashboard/schemas.py`).
- Align all module headers with canonical PEP 8 3-tier import grouping.
- Enforce permanent automated zero-regression prevention via dedicated AST test suite (`tests/test_modernization.py`).
- Update persistent architecture guidelines in `AGENTS.md` and `.agents/rules/security_and_standards.md`.

### 2. Files Touched (26 Files)
- **Dashboard Routers, Services & Schemas (18 files)**:
  - `dashboard/app.py`
  - `dashboard/dependencies.py`
  - `dashboard/routers/__init__.py`
  - `dashboard/routers/analytics.py`
  - `dashboard/routers/camera_diagnostics.py`
  - `dashboard/routers/cameras.py`
  - `dashboard/routers/rsac.py`
  - `dashboard/routers/scenarios.py`
  - `dashboard/routers/streaming.py`
  - `dashboard/routers/system.py`
  - `dashboard/routers/topology.py`
  - `dashboard/routers/videos.py`
  - `dashboard/schemas.py`
  - `dashboard/services/camera_diagnostics.py`
  - `dashboard/services/entity_tagger.py`
  - `dashboard/services/frame_overlay.py`
  - `dashboard/services/stream_subscribers.py`
  - `dashboard/services/video_transcoder.py`
- **Intelligent Tracker Core & Tools (3 files)**:
  - `intelligent_tracker/camera_device.py`
  - `intelligent_tracker/camera_resolver.py`
  - `intelligent_tracker/camera_tool.py`
- **Unit Tests (3 files)**:
  - `tests/test_camera_diagnostics.py`
  - `tests/test_camera_resolver.py`
  - `tests/test_modernization.py` (New AST-based regression test asserting 0 `__future__` imports and 0 legacy shims)
- **Architecture Guidelines & Rules (2 files)**:
  - `AGENTS.md`
  - `.agents/rules/security_and_standards.md`

### 3. Verification & Testing
- **Modernization AST Invariant Tests**:
  - `python -m unittest tests/test_modernization.py`: 2/2 tests passed in 0.734s — **OK (0 failures, 0 errors)**.
- **Subsystem Unit Tests**:
  - `python -m unittest tests/test_camera_tool.py tests/test_camera_resolver.py tests/test_camera_diagnostics.py tests/test_dashboard.py tests/test_scenario_api.py tests/test_vms_api.py`: 44/44 tests passed in 24.8s — **OK (0 failures, 0 errors)**.
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 279 tests in 46.641s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## 2026-11-02: Full Repository Modularity Audit & Core Modernization Campaign Launch

### 1. Objectives & Scope
- Execute a comprehensive AST structural code health audit across the entire repository (148 files, ~37,000+ LOC) via `code_health_audit.py`.
- Identify all legacy God classes, oversized functions, and files breaching quantitative modularity budgets (150–300 lines healthy target, 350 lines soft warning, 500 lines hard ceiling, $\le$ 10–12 methods per class).
- Anchor clean Git baseline (`1fa015e`) and verify 100% green test suite status (279/279 tests passing).
- Formulate a 7-phase zero-regression refactoring roadmap with 1-phase turn gates, re-export facades, and mathematical comment preservation.
- Initialize machine-readable campaign state in `.refactor/state.json` and persist architectural roadmap in `.refactor/plan.md`.

### 2. Audit Findings & Target Monolith Registry
- **Healthy Files**: 121 files within standard budget ($\le$ 350 lines).
- **Soft Warnings**: 10 files (351–500 lines or 10–12 methods).
- **Critical Monoliths (17 files exceeding 500-line hard ceiling or class method limits)**:
  1. `intelligent_tracker/database.py` (2,125 lines, `TrackerDB` has 68 methods)
  2. `intelligent_tracker/geometry.py` (1,816 lines, `BasePoly` has 30 methods, `cnt_intersection` is 316 lines)
  3. `intelligent_tracker/detectors.py` (1,653 lines, `Object` has 35 methods, `Detector` has 17 methods)
  4. `intelligent_tracker/core.py` (1,537 lines, `Group` has 34 methods, `Space` has 17 methods)
  5. `intelligent_tracker/events.py` (1,377 lines, `EventBus` has 11 methods, `TelegramDispatcher` has 228 lines)
  6. `intelligent_tracker/tracker.py` (781 lines, `CentroidTracker.update` is 158 lines)
  7. `tests/test_core.py` (760 lines, `test_compare` is 207 lines)
  8. `dashboard/stream_manager.py` (711 lines, `StreamManager` has 29 methods)
  9. `main.py` (710 lines, `main()` is 511 lines)
  10. `tests/test_events.py` (720 lines, full integration and pipeline tests)
  11. `intelligent_tracker/analytics.py` (641 lines, `AnalyticsEngine` has 404 lines)
  12. `intelligent_tracker/video.py` (635 lines, `VideoSource` has 18 methods)
  13. `intelligent_tracker/matcher.py` (624 lines, `GalleryMatcher` has 543 lines)
  14. `intelligent_tracker/discovery.py` (560 lines, camera probe functions)
  15. `intelligent_tracker/reid.py` (555 lines, `OnnxReIDExtractor` session and pooling)
  16. `intelligent_tracker/high_objects.py` (518 lines, `Scene` has 25 methods)
  17. `intelligent_tracker/periferials.py` (510 lines, `VideoStream` & `SyncCameras`)

### 3. Campaign Roadmap (7 Phases)
- **Phase 1 (Active)**: Persistence & Repository Pattern (`intelligent_tracker/database.py` -> `intelligent_tracker/repositories/`).
- **Phase 2**: Computational Geometry & Polygon Math (`intelligent_tracker/geometry.py` -> `intelligent_tracker/geometry/`).
- **Phase 3**: Object Detection Backends (`intelligent_tracker/detectors.py` -> `intelligent_tracker/detectors/`).
- **Phase 4**: Core Scene Graph & Event Bus Infrastructure (`core.py` & `events.py` -> `core/` & `events/`).
- **Phase 5**: Tracking Engines, ReID Matcher, Video & Discovery (`tracker.py`, `matcher.py`, `video.py`, `discovery.py`).
- **Phase 6**: Application Entrypoint & Streaming Orchestration (`main.py` & `stream_manager.py` -> `cli/` & `services/`).
- **Phase 7**: Test Suite De-crufting & Warning Modules (`tests/`, `scripts/cdp_inspect.py`, JS controllers).

### 4. Verification & Testing
- **Automated Test Baseline**:
  - `python -m unittest discover tests`: Ran 279 tests in 53.1s — **OK (100% green, 0 failures, 0 errors)**.
- **Structural Auditor Validation**:
  - `python "<skill_dir>/scripts/code_health_audit.py" --path . --by-dir`
- **Campaign State**:
  - Initialized `.refactor/state.json` (Phase 1 active, 7 phases total).
  - Saved `.refactor/plan.md`.
## 2026-11-02: App Debugger - Multi-Symptom Runtime Regression Diagnosis & Resolution

### 1. Objectives & Scope
- Diagnose and resolve post-modernization server startup and runtime regressions on Windows.
- Fix Python asyncio Windows IOCP socket accept crashes (`WinError 64` ERROR_NETNAME_DELETED).
- Resolve `StreamManagerWorker` thread termination caused by missing `StreamManager.width` and `StreamManager.height` attributes during diagnostic error frame synthesis.
- Eliminate OpenCV C++ pattern assertion warnings (`icvExtractPattern`) by hardening video file source classification in `VideoSource`.

### 2. Files Modified & Created
- `dashboard/services/windows_resilience.py`:
  - **Created** (127 lines): Lightweight, modular resilience service patching CPython's `BaseProactorEventLoop._start_serving` and `IocpProactor.accept` to absorb transient Windows client drops without terminating the main server listening socket or leaking coroutine exceptions.
- `dashboard/app.py`:
  - Applied `apply_windows_iocp_patch()` upon dashboard initialization.
- `dashboard/stream_manager.py`:
  - Added `@property def width(self) -> int` and `@property def height(self) -> int` with fallback cascade (`video_source` -> `config` -> default `640x480`).
- `intelligent_tracker/video.py`:
  - Hardened `_classify_source()` to ensure sources with video file extensions are properly flagged as `is_file = True` even when absent from disk.
  - Added guard in `_open_capture()` to immediately return `False` when a video file does not exist on disk, preventing invalid OpenCV pattern sequence parsing.
- `tests/test_windows_resilience.py`:
  - **Created** (32 lines): Unit tests for transient Windows socket error codes and patch idempotency.
- `tests/test_hibernation.py`:
  - Added `test_stream_manager_dimensions_and_error_placeholder` verifying dimension properties and placeholder synthesis.
- `tests/test_video.py`:
  - Added `test_nonexistent_video_file_classification_and_safe_open` asserting safe capture rejection without invoking OpenCV.

### 3. Verification & Testing
- **Subsystem Unit Tests**:
  - `python -m unittest tests/test_video.py tests/test_hibernation.py tests/test_windows_resilience.py`: 18/18 tests passed — **OK (0 failures, 0 errors)**.
- **Modernization Invariant Verification**:
  - `python -m unittest tests/test_modernization.py`: 2/2 tests passed — **OK (0 failures, 0 errors)**.
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 283 tests in 49.396s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## 2026-11-02: App Debugger - Graceful Shutdown Hang Resolution & Log Flood Deduplication

### 1. Objectives & Scope
- Eliminate Uvicorn server hang on `CTRL + C` (`Waiting for connections to close. (CTRL+C to force quit)`) and subsequent `KeyboardInterrupt` / `CancelledError` ASGI application crash.
- Resolve mutual shutdown deadlock between Starlette `StreamingResponse` video frame generator and Uvicorn connection draining lifecycle.
- Eliminate high-frequency `FILE_NOT_FOUND` warning flood (25–50 warnings/sec) in `CameraStream._worker_loop` and `CameraHealthManager.set_error()`.
- Implement central `DeduplicatingLogger` service providing rate-limited, state-aware log suppression and recovery resets.
- Add loop backoff and placeholder synthesis guards in `StreamManager` worker loop.

### 2. Files Modified & Created
- `dashboard/services/logger_manager.py`:
  - **Created** (95 lines): Thread-safe singleton `DeduplicatingLogger` with `warning_once`, `error_once`, `info_once`, `log_once`, and `reset` capabilities.
- `dashboard/services/shutdown_handler.py`:
  - **Created** (68 lines): Signal interception service (`install_shutdown_handlers`) wrapping `SIGINT`, `SIGTERM`, and `SIGBREAK` to signal active streams immediately upon the first interrupt signal.
  - Added `GracefulCancellationMiddleware` to absorb benign ASGI `CancelledError` exceptions during server termination or client disconnections.
- `dashboard/services/camera_diagnostics.py`:
  - Routed `CameraHealthManager.set_error()` through `DeduplicatingLogger.warning_once` to log only on error state transitions or code/message changes.
  - Reset deduplication state in `set_online()` so subsequent failures are faithfully reported.
- `dashboard/stream_manager.py`:
  - Guarded `create_error_placeholder_jpeg()` so error placeholder images are not redundantly regenerated 25 times per second.
  - Backed off worker sleep from `0.04s` (25 Hz) to `0.5s` (2 Hz) during persistent camera outage states to save CPU.
- `dashboard/app.py`:
  - Mounted `GracefulCancellationMiddleware` and registered `install_shutdown_handlers()` in `lifespan`.
- `tests/test_logger_manager.py`:
  - **Created** (78 lines): Unit tests asserting log suppression across 100 consecutive calls, message change emission, recovery resets, and `CameraHealthManager` integration.
- `tests/test_shutdown_handler.py`:
  - **Created** (58 lines): Unit tests verifying cancellation absorption and signal handler installation.

### 3. Verification & Testing
- **Target Unit Tests**:
  - `python -m unittest tests/test_logger_manager.py tests/test_shutdown_handler.py tests/test_camera_diagnostics.py`: 11/11 tests passed in 1.7s — **OK (0 failures, 0 errors)**.
- **Modernization Invariant Verification**:
  - `python -m unittest tests/test_modernization.py`: 2/2 tests passed in 0.7s — **OK (0 failures, 0 errors)**.
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 290 tests in 46.004s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## 2026-11-03: Frontier Architect & App Debugger - AnalyticsEngine Parameter Contract & Topology Exit Bridge

### 1. Root Cause & Architectural Rationale
- **Silenced Analytics Execution**:
  - In `dashboard/stream_manager.py`, `self.analytics.update(tracks, frame_time=curr_t, current_frame=frame)` was called inside a `try...except Exception as e: logger.debug(...)` block.
  - `AnalyticsEngine.update` only accepted `tracks` and `timestamp: Optional[float] = None`, causing Python to raise `TypeError: AnalyticsEngine.update() got an unexpected keyword argument 'frame_time'` on every frame.
  - Because `logger.debug` is hidden at default `INFO` logging levels, the error was completely swallowed and spatial analytics (zone dwell tracking, tripwire tallies, occupancy limits, heatmaps) was entirely bypassed during live streaming.
- **Architectural Intention for `current_frame`**:
  - Pipeline stages pass both temporal (`timestamp`/`frame_time`) and visual (`frame`/`current_frame`) context.
  - When an image frame is present during analytics events (`TripwireCrossEvent`, `ZoneEvent`, `RSACViolationEvent`, `PetActivityEvent`, `OccupancyThresholdEvent`), `AnalyticsEngine` should automatically capture and embed visual evidence crops (`snapshot_base64`) using `crop_to_base64`/`frame_to_base64`.
- **Cross-Camera Topology Zone Exit Schema Mismatch**:
  - In `dashboard/stream_manager.py`, the condition `if ev_d.get("event_type") == "zone" and ev_d.get("action") == "exit":` was dead code: `geometry.ZoneEvent.to_dict()` returned `event_type="exit"` with no `action` field, and `events.ZoneEvent` used `event_type="zone_exit"`.
  - Added `@property def action(self) -> str` and `"action": self.event_type` to `geometry.ZoneEvent.to_dict()`, and updated `stream_manager.py` to evaluate `action = ev_d.get("action") or ev_d.get("event_type")` matching `("exit", "zone_exit")`.

### 2. Files Touched
- `intelligent_tracker/analytics.py`:
  - Updated `AnalyticsEngine.update` signature to accept `timestamp: Optional[float] = None, frame_time: Optional[float] = None, current_frame: Optional[np.ndarray] = None, frame: Optional[np.ndarray] = None, **kwargs: Any`.
  - Enriched event bus publishing (`TripwireCrossEvent`, `ZoneEvent`, `PetActivityEvent`, `RSACViolationEvent`, `OccupancyThresholdEvent`) to generate and attach `snapshot_base64` visual crops when `current_frame` is provided.
- `intelligent_tracker/geometry.py`:
  - Added `@property def action(self) -> str` returning `self.event_type`.
  - Included `"action": self.event_type` in `ZoneEvent.to_dict()` for cross-subsystem schema parity.
- `dashboard/stream_manager.py`:
  - Standardized the call to `self.analytics.update(tracks, timestamp=curr_t, current_frame=frame)`.
  - Updated zone exit check to `action = ev_d.get("action") or ev_d.get("event_type"); if action in ("exit", "zone_exit"):` to ensure Milestone 8 cross-camera predictive priors reliably fire.
  - Replaced swallowed `logger.debug` with visible `logger.warning(..., exc_info=True)` to prevent silent failures.
- `tests/test_analytics.py`:
  - Added `test_zone_event_action_property_and_to_dict` verifying schema parity.
  - Added `test_analytics_engine_update_with_frame_time_and_current_frame` verifying parameter resilience and snapshot generation on event bus.
- `tests/test_dashboard.py`:
  - Added `test_12_stream_manager_analytics_update_and_topology_exit_trigger` verifying that stream manager analytics updates trigger topology priors on zone exit.

### 3. Verification & Testing
- `python -m unittest tests/test_analytics.py tests/test_dashboard.py`: 20/20 tests passed — **OK (0 failures, 0 errors)**.
- `python -m unittest tests/test_topology.py tests/test_events.py`: 27/27 tests passed — **OK (0 failures, 0 errors)**.
- `python -m unittest tests/test_modernization.py`: 2/2 tests passed — **OK (0 failures, 0 errors)**.
- `python -m unittest discover tests`: 292/292 tests passed — **OK (100% green)**.
## 2026-11-03: Frontier Architect & App Debugger - Tier 2 Graceful Server Shutdown & Concurrency Architecture

### 1. Root Cause & Architectural Rationale
- **Sequential $O(N)$ Teardown Bottleneck**:
  - `CameraPool.stop_all()` previously stopped all configured camera streams sequentially on the main asyncio thread. For 7 streams with reconnect and error timeouts, teardown took 15–25+ seconds.
  - Re-architected `CameraPool.stop_all(parallel=True)` with a two-pass strategy: Pass 1 broadcasts `signal_stop()` simultaneously across all streams in $< 1\text{ms}$; Pass 2 executes concurrent teardown via `ThreadPoolExecutor(max_workers=min(8, len(mgrs)))`.
- **Uninterruptible Sleep in Worker Loops**:
  - `VideoSource._capture_worker` and `StreamManager._worker_loop` relied on `time.sleep()`, which could not be interrupted by `_running = False` flags, forcing joins to wait full sleep intervals (up to 2.0s per stream).
  - Introduced `_stop_event = threading.Event()` in both `VideoSource` and `StreamManager`, replacing `time.sleep()` with `self._stop_event.wait(timeout=...)`. Thread wake-up on shutdown now occurs in $< 10\text{ms}$ (0ms syscall unblock).
- **Orphaned EventBus Worker Threads**:
  - `StreamManager.stop()` stopped the rule engine but failed to invoke `stop()` on `self.event_pipeline["event_bus"]`, leaking `EventBusWorker` daemon threads on server exit.
  - Added explicit `event_bus.stop()` in `StreamManager.stop()`.
- **Asynchronous Event Loop Protection & Watchdog Guard**:
  - Moved heavy hardware capture teardowns off the asyncio event loop thread using `async_shutdown_pool(camera_pool)` backed by `asyncio.to_thread()`, keeping Uvicorn's event loop unblocked to rapidly close HTTP keep-alive connections.
  - Implemented `start_watchdog_guard(timeout=4.0)` to ensure that if a proprietary third-party OS driver (DirectShow/MSMF/V4L2) hangs in kernel space, the process cleanly and safely terminates via `os._exit(0)` without leaving the terminal frozen.

### 2. Files Touched
- `intelligent_tracker/video.py`:
  - Added `self._stop_event` and `signal_stop()` method to `VideoSource`.
  - Replaced reconnect `time.sleep(self.reconnect_delay)` with interruptible `_stop_event.wait()`.
- `dashboard/stream_manager.py`:
  - Added `self._stop_event` and `signal_stop()` method to `StreamManager`.
  - Replaced loop throttling and error placeholder sleeps with `_stop_event.wait()`.
  - Ensured `self.event_pipeline["event_bus"].stop()` is called cleanly during teardown.
- `dashboard/camera_pool.py`:
  - Implemented `signal_stop_all()` for broadcast signaling.
  - Re-architected `stop_all(parallel=True)` using `concurrent.futures.ThreadPoolExecutor` for parallel multi-camera join.
- `dashboard/services/shutdown_handler.py`:
  - Added `broadcast_shutdown()` to instantly signal all subsystems upon `SIGINT`/`SIGTERM`/`SIGBREAK`.
  - Added `async_shutdown_pool()` for non-blocking lifespan shutdown.
  - Added `start_watchdog_guard()` with test-environment detection.
- `dashboard/app.py`:
  - Integrated `await async_shutdown_pool(camera_pool)` in `lifespan()` shutdown context.
- `tests/test_graceful_shutdown_perf.py`:
  - **Created** (150 lines): Validates sub-millisecond interruptible sleep in `VideoSource` & `StreamManager`, concurrent parallel scaling in `CameraPool`, event loop non-blocking behavior, zero leaked EventBus workers, and watchdog initiation.
- `tests/test_shutdown_handler.py`:
  - Added tests for `async_shutdown_pool`, `start_watchdog_guard`, and broadcast handlers.

### 3. Verification & Testing
- **Performance & Graceful Shutdown Unit Tests**:
  - `python -m unittest tests/test_graceful_shutdown_perf.py tests/test_shutdown_handler.py`: 11/11 tests passed in 2.7s — **OK (0 failures, 0 errors)**.
- **Modernization Invariant Verification**:
  - `python -m unittest tests/test_modernization.py`: 2/2 tests passed in 1.6s — **OK (0 failures, 0 errors)**.
- **Full Project Test Suite**:
  - `python -m unittest discover tests`: Ran 301 tests in 51.504s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
- **Real-World Uvicorn 7-Camera Teardown**:
  - Live server process with 7 configured cameras cleanly stopped and exited in **1.72s** (down from 20–30s+ hang).
## 2026-11-03: App Debugger - Fix Watchdog False-Positive Test Detection & VideoSource Shutdown Waits

### 1. Root Cause & Architectural Triage
- **Watchdog `is_test_environment()` False Positive**:
  - `is_test_environment()` previously checked `"unittest" in sys.modules`.
  - When `intelligent_tracker` or `dashboard.app` initializes, transitive dependencies (e.g., `numpy.testing`, `pyparsing.testing`) unconditionally import `unittest`, placing `'unittest'` in `sys.modules` for every production run.
  - As a result, `is_test_environment()` returned `True` in production, causing the watchdog to log `"Graceful shutdown watchdog timeout (4.0s) reached; forcing clean process exit."` but skip `os._exit(0)`, leaving lingering Python processes alive with unjoined background threads.
  - Refactored `is_test_environment()` to strictly inspect active test runner entrypoints (`__main__.__file__` and `sys.argv`), returning `False` in production while protecting test suite runners.
- **Uninterruptible Worker Sleeps in VideoSource**:
  - `VideoSource._capture_worker` still contained residual `time.sleep()` calls in frame-rate pacing (`min_frame_time`), empty frame retries, and reconnect backoffs.
  - Replaced all remaining worker sleeps with `self._stop_event.wait(timeout=...)` to ensure immediate loop break on `signal_stop()`.
- **Driver Lock Settle Delay Optimization**:
  - `CameraDeviceHandler.safe_release()` previously slept `0.15s` - `0.25s` per camera under `_device_lock`. During process shutdown, settling DirectShow hardware for immediate re-opening is unnecessary. Set `settle_delay=0.0` on teardown to eliminate serialized multi-camera unbind delays.
- **Bounded Join Timeouts**:
  - Reduced thread join timeouts in `StreamManager.stop()` and `VideoSource.stop()` from `1.5s` to `0.6s`.

### 2. Files Touched
- `dashboard/services/shutdown_handler.py`:
  - Fixed `is_test_environment()` to check `sys.argv` and `__main__.__file__` instead of `"unittest" in sys.modules`.
  - Added stdout/stderr flushing before `os._exit(0)`.
  - Improved `get_console_logger()` to resolve handlers across parent logger hierarchies and root logger.
- `intelligent_tracker/video.py`:
  - Replaced `time.sleep()` in `_capture_worker` with `_stop_event.wait()`.
  - Set `settle_delay=0.0` during stream stop.
  - Bounded join timeout to `0.6s`.
- `dashboard/camera_pool.py`:
  - Enabled parallel concurrent teardown for all non-empty stream pools.
- `dashboard/stream_manager.py`:
  - Bounded worker thread join timeout to `0.6s`.
- `tests/test_shutdown_handler.py`:
  - Added `test_is_test_environment_detection` and `test_watchdog_triggers_exit_in_production`.
- `tests/test_graceful_shutdown_perf.py`:
  - Added `test_camera_pool_single_stream_and_sequential_fallback` covering single-stream and sequential fallback branches.

### 3. Verification & Testing
- **Shutdown Handler & Performance Tests**:
  - `python -m unittest -v tests/test_shutdown_handler.py tests/test_graceful_shutdown_perf.py`: 14/14 tests passed in 0.8s — **OK (0 failures, 0 errors)**.
- **Full Test Suite**:
  - `python -m unittest discover tests`: 304/304 tests passed in 40.2s — **OK (100% green)**.
## 2026-11-03: Refactor Monolith - Phase 1: Persistence Layer & Repository Pattern (intelligent_tracker/database.py)

### 1. Root Cause & Architectural Triage
- **Monolith Deconstruction**:
  - `intelligent_tracker/database.py` was a 2,125-line God class with 68 methods (`TrackerDB`), mixing SQLite DDL, entity enrollment, feature embedding serialization, gallery matrices, sightings audit trails, Scenario Studio zones/tripwires/transitions, homography calibrations, active learning queues, RSAC permissions, pet whitelists, local offline credential caches, and telemetry.
  - Decomposed into cohesive domain mixins under `intelligent_tracker/repositories/` adhering strictly to quantitative modularity budgets (all files $\le 350$ lines, classes $\le 12$ methods).
- **Zero-Breaking-Import Facade**:
  - Retained `TrackerDB` as a 128-line composition facade inheriting from all domain mixins. 100% of existing imports and public APIs (`serialize_embedding`, `deserialize_embedding`, `add_entity`, `get_sightings`, etc.) remain identical and backwards-compatible.

### 2. Files Modified & Created
- `intelligent_tracker/database.py`:
  - Reduced from 2,125 lines down to 128 lines; acts as a composition facade.
- `intelligent_tracker/repositories/schema_manager.py` (Created, 322 lines):
  - `SchemaMixin`: SQLite DDL table setup, indexes, migrations, and seed data.
- `intelligent_tracker/repositories/entity_repo.py` (Created, 239 lines):
  - `EntityMixin`: Entity registration, updates, retrieval, deletion, and high-level enrollment helper.
- `intelligent_tracker/repositories/signature_repo.py` (Created, 216 lines):
  - `SignatureMixin`: Re-ID feature embedding serialization, signatures, and gallery matrices.
- `intelligent_tracker/repositories/descriptor_repo.py` (Created, 164 lines):
  - `DescriptorMixin`: Historical descriptor versions, continuous learning drift audits, and memory rollback.
- `intelligent_tracker/repositories/analytics_repo.py` (Created, 230 lines):
  - `AnalyticsMixin`: Sightings audit trail, entity analytics, dwell time calculations, and CSV/JSON exports.
- `intelligent_tracker/repositories/spatial_repo.py` (Created, 277 lines):
  - `SpatialMixin`: Scenario Studio zones, tripwires, cross-camera transitions, and homography calibrations.
- `intelligent_tracker/repositories/learning_repo.py` (Created, 159 lines):
  - `LearningMixin`: Active learning review inbox and role-based custom categories.
- `intelligent_tracker/repositories/rsac_repo.py` (Created, 146 lines):
  - `RsacMixin`: Role-based spatial access control rules and pet whitelists.
- `intelligent_tracker/repositories/whitelist_repo.py` (Created, 241 lines):
  - `WhitelistMixin`: Offline-first local whitelist, cloud sync state, and offline access queue.
- `intelligent_tracker/repositories/telemetry_repo.py` (Created, 115 lines):
  - `TelemetryMixin`: Hardware resource telemetry and stream lifecycle events.
- `intelligent_tracker/repositories/__init__.py` (Created, 31 lines):
  - Package re-exports for all mixins.

### 3. Verification & Testing
- **Modularity Audit**:
  - `python <skill_dir>/scripts/code_health_audit.py --path intelligent_tracker/database.py intelligent_tracker/repositories/ --show-methods`:
  - Result: 12/12 files OK, 0 Critical, 0 Warnings.
- **Contract & Regression Parity**:
  - `python <skill_dir>/scripts/contract_snapshot.py verify --path . --strict`:
  - Result: Tier 1 AST & DOM Invariant Parity: VERIFIED (Zero regressions).
- **Targeted Persistence & Integration Tests**:
  - `test_database.py` (11/11 OK in 1.2s)
  - `test_backup.py` (6/6 OK in 0.8s)
  - `test_scenarios.py` (5/5 OK in 0.4s)
  - `test_active_learning.py` (5/5 OK in 0.4s)
  - `test_rsac.py` (6/6 OK in 0.4s)
  - `test_enrollment.py` (3/3 OK in 0.8s)
  - `test_m9_api.py` (4/4 OK in 0.3s)
  - `test_topology.py` (8/8 OK in 0.003s)
  - `test_journey.py` (3/3 OK in 0.3s)
  - `test_refactor_contract.py` (3/3 OK in 0.02s)
  - `test_modernization.py` (2/2 OK in 0.8s)
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 304 tests in 41.846s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## 2026-11-03: Refactor Monolith - Phase 2: Computational Geometry & Polygon Mathematics (intelligent_tracker/geometry/)

### 1. Root Cause & Architectural Triage
- **Monolith Deconstruction**:
  - `intelligent_tracker/geometry.py` was an 1,823-line God module containing complex Bézier line clipping, Sutherland-Hodgman polygon graph intersections, port-linked bidirectional connection solvers, recursive traversal routines, and retail spatial analytics (`Tripwire`, `ZoneROI`).
  - `BasePoly` had 30 items/methods and 531 lines, mixing port indexing, connection resolution, inversion, and recursive traversals.
  - Decomposed into cohesive domain submodules under `intelligent_tracker/geometry/` adhering strictly to quantitative modularity budgets (all files $\le 350$ lines, classes $\le 10-12$ methods).
- **Zero-Breaking-Import Facade**:
  - Converted `intelligent_tracker/geometry.py` into package `intelligent_tracker/geometry/__init__.py` (84 lines) re-exporting 100% of public primitives, exceptions, polygon graph solvers, raster operations, and retail zone classes.
  - Preserved all mathematical docstrings, Bézier/Line-intersection formulas, and computer vision proofs verbatim.
  - Zero broken imports across all callers (`stream_manager.py`, `analytics.py`, `core.py`, `high_objects.py`, `interactive.py`, `scenarios.py`, `main.py`).

### 2. Files Modified & Created
- `intelligent_tracker/geometry/__init__.py` (Created via `git mv`, 84 lines):
  - Clean re-export facade with complete `__all__` registry.
- `intelligent_tracker/geometry/primitives.py` (Created, 181 lines):
  - `NotInvertible`, `IncompleteAssociations`, `norm_point`, `bezier`, `line_intersection`, `cnt_group`, `go_around`, `segments_intersect`.
- `intelligent_tracker/geometry/indexing.py` (Created, 165 lines):
  - `generate_poly_indexes`, `resolve_poly_connections`.
- `intelligent_tracker/geometry/polygons.py` (Created, 278 lines):
  - `PolyPortAccessMixin` (8 items), `PolyPortLinkMixin` (7 items), `PolyTraversalMixin` (5 items), `BasePoly` (10 items), `Interception`, `PolyLine`.
- `intelligent_tracker/geometry/associations.py` (Created, 184 lines):
  - `Completeness` (11 items), `_associate_single_references`, `_associate_complex_groups`.
- `intelligent_tracker/geometry/raster.py` (Created, 68 lines):
  - `draw_drawContours`, `draw_fillConvexPoly`, `draw_fillPoly`, `intersect_AND`, `intersect_ADD`.
- `intelligent_tracker/geometry/intersections.py` (Created, 288 lines):
  - `EspList`, `cnt_check_intersection`, `cnt_intersection`, `intersect_analytical`, `mixed_intersections`.
- `intelligent_tracker/geometry/tripwire.py` (Created, 170 lines):
  - `TripwireEvent`, `Tripwire` (6 items).
- `intelligent_tracker/geometry/zone_roi.py` (Created, 216 lines):
  - `ZoneEvent`, `ZoneROI` (9 items).
- `intelligent_tracker/geometry/zones.py` (Created, 11 lines):
  - Convenience domain re-export module.

### 3. Verification & Testing
- **Modularity Audit**:
  - `python <skill_dir>/scripts/code_health_audit.py --path intelligent_tracker/geometry --show-methods`:
  - Result: 10/10 files OK (all $\le 288$ lines, healthy budget $\le 350$ lines), 0 Critical, 0 Warnings.
- **Contract & Regression Parity**:
  - `python <skill_dir>/scripts/contract_snapshot.py verify --path . --strict`:
  - Result: Tier 1 AST & DOM Invariant Parity: VERIFIED (Zero regressions).
- **Targeted Geometry & Analytics Tests**:
  - `tests/test_geometry.py` (3/3 OK in 0.02s)
  - `tests/test_analytics.py` (8/8 OK in 0.20s)
  - `tests/test_interactive.py` (6/6 OK in 0.20s)
  - `tests/test_scenarios.py` (5/5 OK in 0.15s)
  - `tests/test_homography.py` (6/6 OK in 0.05s)
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 304 tests in 40.276s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## 2026-11-03: Refactor Monolith - Phase 3: Object Detection Backends & Representations (intelligent_tracker/detectors/)

### 1. Root Cause & Architectural Triage
- **Monolith Deconstruction**:
  - `intelligent_tracker/detectors.py` was a 1,653-line God module coupling `Object` bounding box and kinematics representations, `Detector` space-lifecycle management, ONNX runtime deep learning backends (`OnnxDetector`), hardware-accelerated Coral Edge TPU runtime (`EdgeTpuDetector`), OpenCV Haar Cascades, affine perspective generators, and color thresholding into a single file.
  - `Object` had 35 methods/properties across 438 lines, violating the Single Responsibility Principle by combining OpenCV multi-tracker initializations, direction delta estimations, canvas drawing, and spatial containment queries.
  - `OnnxDetector.detect` was a 99-line monolithic method handling image letterboxing, inference execution, prediction transposition, confidence filtering, bounding box remapping, and vectorized NMS.
  - Decomposed into cohesive domain submodules under `intelligent_tracker/detectors/` adhering strictly to quantitative modularity budgets (all files $\le 344$ lines, classes $\le 10$ methods, functions $\le 35$ lines).
- **Zero-Breaking-Import Facade**:
  - Transformed `intelligent_tracker/detectors.py` into package `intelligent_tracker/detectors/__init__.py` (74 lines) re-exporting 100% of public detector classes, factory registry, and object tracking representations with complete backwards compatibility.
  - Preserved all OpenCV cascade paths, coordinate clamping proofs, and Edge AI inference contracts verbatim.
  - Maintained zero broken imports across all callers (`tests/test_detectors.py`, `tests/test_tracker.py`, `high_objects.py`, `interactive.py`, `reid.py`, `main.py`).

### 2. Files Modified & Created
- `intelligent_tracker/detectors/__init__.py` (Created, 74 lines):
  - Clean re-export facade with complete `__all__` registry.
- `intelligent_tracker/detectors/base.py` (Created, 66 lines):
  - `BaseDetector` abstract interface, `Detection` namedtuple, and `DetectorFactory` decoupled registry.
- `intelligent_tracker/detectors/objects.py` (Created, 100 lines):
  - `Object` entity representation, track lifecycle, and coordinate bounding boxes.
- `intelligent_tracker/detectors/object_mixins.py` (Created, 344 lines):
  - `ObjectDynamicsMixin` (8 items), `ObjectGeometryMixin` (7 items), `ObjectVisualMixin` (6 items), `ObjectSpatialMixin` (6 items), `ObjectKinematicsMixin` (4 items).
- `intelligent_tracker/detectors/core_detector.py` (Created, 225 lines):
  - `DetectorObjectLifecycleMixin` (6 items), `DetectorProcessingMixin` (6 items), `Detector` base class (6 items).
- `intelligent_tracker/detectors/haar.py` (Created, 213 lines):
  - `HaarCascadeDetector` (3 items), `InvariantCascade` (3 items), `EyeDetector` (2 items), `FaceDetector` (2 items), `affine`.
- `intelligent_tracker/detectors/yunet.py` (Created, 114 lines):
  - `YuNetFaceDetector` (4 items) with OpenCV cv2.FaceDetectorYN support and Haar fallback cascade.
- `intelligent_tracker/detectors/color_detector.py` (Created, 96 lines):
  - `ColorDetector` (10 items) for HSV range thresholding and candidate filtering.
- `intelligent_tracker/detectors/mock_detector.py` (Created, 70 lines):
  - `MockDetector` (3 items) for deterministic simulation and headless testing.
- `intelligent_tracker/detectors/onnx_detector.py` (Created, 342 lines):
  - `OnnxDetector` (7 items), `letterbox`, `nms_numpy`, `_create_yolov8_detector`, `_create_yolo11_detector`.
- `intelligent_tracker/detectors/edgetpu_detector.py` (Created, 120 lines):
  - `EdgeTpuDetector` (5 items) for hardware-accelerated Coral TPU runtime.
- `intelligent_tracker/detectors/legacy_detectors.py` (Created, 20 lines):
  - `PeopleDetector`, `ObjectDetector`, `MovementDetector` backwards compatibility stubs.
- `intelligent_tracker/detectors/coco_classes.py` (Created, 13 lines):
  - Standard 80-class COCO labels.

### 3. Verification & Testing
- **Modularity Audit**:
  - `python <skill_dir>/scripts/code_health_audit.py --path intelligent_tracker/detectors --show-methods`:
  - Result: 13/13 files OK (all $\le 344$ lines, healthy budget $\le 350$ lines), 0 Critical, 0 Warnings.
- **Contract & Regression Parity**:
  - `python <skill_dir>/scripts/contract_snapshot.py verify --path . --strict`:
  - Result: Tier 1 AST & DOM Invariant Parity: VERIFIED (Zero regressions).
- **Targeted Detector Tests**:
  - `tests/test_detectors.py` (25/25 OK in 1.18s)
  - `tests/test_tracker.py` (9/9 OK in 0.002s)
  - `tests/test_modernization.py` (2/2 OK in 0.80s)
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 304 tests in 40.524s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## 2026-11-03: Refactor Monolith - Phase 4: Core Scene Graph & Event Bus Infrastructure (intelligent_tracker/core/ & intelligent_tracker/events/)

### 1. Root Cause & Architectural Triage
- **Monolith Deconstruction**:
  - `intelligent_tracker/core.py` was a 1,537-line God module combining hierarchical spatial graphs (`Space`), collections (`Group`, `CompleteGroup`), agent visual representations (`Agent`), trajectory items (`TailItem`), and weak-reference dictionary watchers.
  - `Group` had 34 methods/properties across 373 lines, while `Space` had 17 methods across 333 lines.
  - `intelligent_tracker/events.py` was a 1,377-line God module mixing typed event dataclasses, centralized async `EventBus`, HTTP `WebhookDispatcher` with exponential backoff retries, `TelegramDispatcher` with Markdown formatting and `/status` command handling, `MqttPublisher` for Home Assistant/IoT telemetry, and `AlertRuleEngine` quiet hours evaluator.
  - Decomposed both monoliths into clean, SRP-compliant domain packages (`intelligent_tracker/core/` and `intelligent_tracker/events/`) adhering strictly to modularity budgets ($\le 261$ lines across all 17 submodules).
- **Zero-Breaking-Import Facade**:
  - `intelligent_tracker/core/__init__.py` (65 lines) re-exports 100% of spatial primitives, groups, agents, trajectory types, and OpenCV version helpers with complete backwards compatibility.
  - `intelligent_tracker/events/__init__.py` (58 lines) re-exports 100% of event dataclasses, event bus, dispatchers, rule engines, and snapshot helpers.
  - Maintained zero broken imports across all callers (`tests/test_core.py`, `tests/test_events.py`, `detectors/`, `analytics.py`, `stream_manager.py`, `discovery.py`, `main.py`).

### 2. Files Modified & Created
- `intelligent_tracker/core/__init__.py` (Created, 65 lines): Re-export facade with complete `__all__` registry.
- `intelligent_tracker/core/weakref_utils.py` (Created, 252 lines): `SpaceHandle`, `WeakWatcher`, `WeakWatcherWithData`, `WeakWatcherDictionary`, `WeakRefDictionary`.
- `intelligent_tracker/core/space_hierarchy.py` (Created, 131 lines): `SpaceHierarchyMixin` for hierarchy traversal, child registration, and family tree queries.
- `intelligent_tracker/core/spaces.py` (Created, 189 lines): `MetaSpace`, `Space`, `deco_name`.
- `intelligent_tracker/core/group_mutations.py` (Created, 172 lines): `GroupMutationMixin` for item addition, removal, and pending mutation dispatch.
- `intelligent_tracker/core/groups.py` (Created, 182 lines): `GroupHandle`, `Group` collection and iteration logic.
- `intelligent_tracker/core/complete_groups.py` (Created, 165 lines): `CompleteGroup` for high-performance indexing and index retrieval.
- `intelligent_tracker/core/agents.py` (Created, 125 lines): `Agent` spatial representation with bounding boxes, rotated rectangles, and contours.
- `intelligent_tracker/core/tails.py` (Created, 187 lines): `Point`, `TailItem` trajectory history and geometric intersection checks.
- `intelligent_tracker/events/__init__.py` (Created, 58 lines): Re-export facade with complete `__all__` registry.
- `intelligent_tracker/events/types.py` (Created, 250 lines): `frame_to_base64`, `crop_to_base64`, `decode_snapshot_base64`, `BaseEvent`, `ZoneEvent`, `TripwireCrossEvent`, `IntrusionAlert`, `OccupancyThresholdEvent`, `EntityIdentifiedEvent`, `RestrictedEntityAlert`, `RSACViolationEvent`, `PetActivityEvent`, `ReviewItemQueuedEvent`.
- `intelligent_tracker/events/bus.py` (Created, 174 lines): `EventBus` pub/sub engine with thread-safe queue, async worker threads, and error isolation.
- `intelligent_tracker/events/webhooks.py` (Created, 177 lines): `WebhookDispatcher` with HTTP POST retries, HMAC-SHA256 signatures, and backoff.
- `intelligent_tracker/events/telegram.py` (Created, 261 lines): `TelegramDispatcher` with Markdown formatting, snapshot uploads, cooldown deduplication, and `/status` bot query responder.
- `intelligent_tracker/events/mqtt.py` (Created, 214 lines): `MqttPublisher` for Home Assistant / Node-RED telemetry, retained occupancy, sightings, and LWT.
- `intelligent_tracker/events/rules.py` (Created, 222 lines): `QuietHours`, `AlertRule`, `AlertRuleEngine` for time-of-day schedules and dynamic alert generation.
- `intelligent_tracker/events/pipeline.py` (Created, 120 lines): `setup_event_pipeline` configuration factory.

### 3. Verification & Testing
- **Modularity Audit**:
  - `python <skill_dir>/scripts/code_health_audit.py --path intelligent_tracker/core intelligent_tracker/events`:
  - Result: 17/17 files OK (all $\le 261$ lines, healthy budget $\le 350$ lines), 0 Critical, 0 Warnings.
- **Contract & Regression Parity**:
  - `python <skill_dir>/scripts/contract_snapshot.py verify --path . --strict`:
  - Result: Tier 1 AST & DOM Invariant Parity: VERIFIED (Zero regressions).
- **Targeted Core & Events Tests**:
  - `tests/test_core.py` (17/17 OK in 1.48s)
  - `tests/test_events.py` (19/19 OK in 1.26s)
  - `tests/test_detectors.py` (25/25 OK in 0.88s)
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 304 tests in 44.184s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## 2026-11-03: Refactor Monolith - Phase 5 (Sub-Phase 5.1): Tracking Engines & Threaded Video Ingestion (intelligent_tracker/tracker/ & intelligent_tracker/video/)

### 1. Root Cause & Architectural Triage
- **Monolith Deconstruction**:
  - `intelligent_tracker/tracker.py` was a 781-line God module containing object tracking representations (`Track`), Euclidean/IoU centroid association (`CentroidTracker` with a 158-line `update` method), 2D kinematic Kalman filters (`KalmanBoxTracker`), SORT tracking (`SortTracker` with a 93-line `update` method), occlusion reasoning (`check_track_occlusions`), and tracker factory registration (`TrackerFactory`).
  - `intelligent_tracker/video.py` was a 653-line God module combining threaded RTSP/file ingestion, auto-reconnect exponential backoff loops, hardware probe heuristics, deep capture hibernation, and high-fidelity synthetic frame generation (`SyntheticFrameGenerator`).
  - Decomposed both monoliths into clean, SRP-compliant domain packages (`intelligent_tracker/tracker/` and `intelligent_tracker/video/`) with a forwarding alias `intelligent_tracker/tracking.py`.
  - All files strictly adhere to modularity budgets ($\le 307$ lines across all 15 submodules; classes $\le 10$ methods; functions $\le 38$ lines; 0 critical breaches).
- **Zero-Breaking-Import Facades**:
  - `intelligent_tracker/tracker/__init__.py` (30 lines) re-exports 100% of tracking primitives, filters, association algorithms, and factories.
  - `intelligent_tracker/tracking.py` (27 lines) provides an ergonomic forwarding alias for callers importing `intelligent_tracker.tracking`.
  - `intelligent_tracker/video/__init__.py` (23 lines) re-exports 100% of video ingestion sources, synthetic generators, and physical camera resolvers.
  - Preserved all OpenCV coordinate mathematics, IoU formulas, Kalman state transition proofs, and thread-safety invariants verbatim.

### 2. Files Modified & Created
- `intelligent_tracker/tracker/__init__.py` (Created, 30 lines): Re-export facade with complete `__all__` registry.
- `intelligent_tracker/tracker/utils.py` (Created, 81 lines): `compute_iou`, `compute_iou_matrix`, `greedy_assignment`, Hungarian SciPy import/fallback.
- `intelligent_tracker/tracker/occlusion.py` (Created, 93 lines): `check_track_occlusions`, `_find_cluttered_pairs`, `_evaluate_track_separation` for Milestone 9 clutter reasoning.
- `intelligent_tracker/tracker/track.py` (Created, 158 lines): `Track` object tracking representation, velocity smoothing, dead-reckoning extrapolation, and session telemetry.
- `intelligent_tracker/tracker/centroid.py` (Created, 263 lines): `CentroidTracker` two-stage IoU and Euclidean association engine with decomposed helper methods ($\le 37$ lines each).
- `intelligent_tracker/tracker/sort.py` (Created, 259 lines): `KalmanBoxTracker` 7-state kinematic filter and `SortTracker` online association engine.
- `intelligent_tracker/tracker/factory.py` (Created, 38 lines): `TrackerFactory` dynamic registration registry.
- `intelligent_tracker/tracking.py` (Created, 27 lines): Ergonomic package forwarding facade.
- `intelligent_tracker/video/__init__.py` (Created, 23 lines): Re-export facade with complete `__all__` registry.
- `intelligent_tracker/video/devices.py` (Created, 72 lines): `is_physical_camera`, `find_physical_cameras`, `find_first_real_camera`, `resolve_camera_source`.
- `intelligent_tracker/video/synthetic.py` (Created, 81 lines): `SyntheticFrameGenerator` high-fidelity automated testing and CI simulation generator.
- `intelligent_tracker/video/hibernation.py` (Created, 37 lines): `StreamHibernationMixin` pause/resume capture thread control.
- `intelligent_tracker/video/lifecycle.py` (Created, 128 lines): `CaptureLifecycleMixin` thread startup, wait_ready, signal_stop, safe release, and context management.
- `intelligent_tracker/video/capture_worker.py` (Created, 307 lines): `CaptureWorkerMixin` capture loop, source classification, auto-reconnect backoff, and frame buffer queueing.
- `intelligent_tracker/video/source.py` (Created, 122 lines): `VideoSource` thread-safe non-blocking reader and telemetry metrics provider.

### 3. Verification & Testing
- **Modularity Audit**:
  - `python <skill_dir>/scripts/code_health_audit.py --path intelligent_tracker/tracker/ intelligent_tracker/tracking.py intelligent_tracker/video/ --show-methods`:
  - Result: 15/15 files OK, 0 Critical breaches across all files, functions, and classes.
- **Contract & Regression Parity**:
  - `python <skill_dir>/scripts/contract_snapshot.py verify --path . --strict`:
  - Result: Tier 1 AST & DOM Invariant Parity: VERIFIED (Zero regressions).
- **Targeted Test Suites**:
  - `tests/test_tracker.py` (9/9 OK in 0.002s)
  - `tests/test_occlusion_and_ema.py` (4/4 OK in 0.47s)
  - `tests/test_video.py` (10/10 OK in 0.44s)
  - `tests/test_camera_device.py` (41/41 OK in 19.75s)
  - `tests/test_hibernation.py` (6/6 OK in 1.87s)
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 304 tests in 48.280s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## 2026-11-04: Refactor Monolith - Phase 5 (Sub-Phase 5.2): Visual Re-ID Feature Extractors & Gallery Matcher (intelligent_tracker/reid/ & intelligent_tracker/matching/)

### 1. Root Cause & Architectural Triage
- **Monolith Deconstruction**:
  - `intelligent_tracker/reid.py` was a 555-line God module combining cosine similarity matrix utilities, abstract extractor contracts (`BaseFeatureExtractor`), spatial HSV color histogram extractors (`ColorHistogramExtractor`), deep ONNX model inference with multi-provider cascade (`OnnxReIDExtractor`), synthetic test extractors (`MockFeatureExtractor`), dual-model appearance & localized face extractors (`DualModelFeatureExtractor`), and extractor registry factories (`ReIDExtractorFactory`).
  - `intelligent_tracker/matcher.py` was a 624-line God module containing identification event and session entity dataclasses (`EntityIdentifiedEvent`, `SessionEntity`), bounded exponential moving average adaptive memory (`_apply_bounded_ema_update` of 78 lines), and a monolithic 543-line `GalleryMatcher` class with a 236-line `match_track` method combining active learning, cross-camera topology spatial priors, database sighting logging, and in-memory dead-reckoning session tracking.
  - Decomposed both monoliths into clean, SRP-compliant domain packages (`intelligent_tracker/reid/` and `intelligent_tracker/matching/`) with a 100% backward-compatible facade in `intelligent_tracker/matcher.py` and `intelligent_tracker/reid/__init__.py`.
  - All extracted modules adhere to quantitative modularity budgets: files $\le 426$ lines (healthy targets $\le 350-500$ lines), `GalleryMatcher` class reduced to 10 methods (exact healthy target budget $\le 10$), and all functions and helper methods $\le 38$ lines.
- **Zero-Breaking-Import Facades**:
  - `intelligent_tracker/reid/__init__.py` (25 lines) re-exports 100% of visual feature extractors, cosine similarity metrics, and extractor factories with complete `__all__` registry.
  - `intelligent_tracker/matcher.py` (21 lines) re-exports 100% of public gallery matching coordinators, session entities, and identification events from `intelligent_tracker.matching`.
  - Preserved all OpenCV image preprocessing, ImageNet normalization vectors, ONNX session provider cascade hierarchy (CUDA -> DirectML -> OpenVINO -> CoreML -> CPU), cosine similarity proofs, and locked-anchor drift bounds verbatim.

### 2. Files Modified & Created
- `intelligent_tracker/reid/__init__.py` (Created, 25 lines): Re-export facade with complete `__all__` registry.
- `intelligent_tracker/reid/metrics.py` (Created, 60 lines): `cosine_similarity` and `batch_cosine_similarity` vector distance metrics.
- `intelligent_tracker/reid/base.py` (Created, 50 lines): `BaseFeatureExtractor` abstract base interface.
- `intelligent_tracker/reid/color.py` (Created, 88 lines): `ColorHistogramExtractor` spatial-grid HSV descriptor with sub-millisecond execution.
- `intelligent_tracker/reid/onnx_extractor.py` (Created, 171 lines): `OnnxReIDExtractor` deep visual feature extractor running ONNX models with multi-provider execution cascade.
- `intelligent_tracker/reid/mock.py` (Created, 42 lines): `MockFeatureExtractor` deterministic synthetic feature extractor for tests and headless CI.
- `intelligent_tracker/reid/dual.py` (Created, 92 lines): `DualModelFeatureExtractor` combining body visual appearance with localized YuNet face intelligence.
- `intelligent_tracker/reid/factory.py` (Created, 39 lines): `ReIDExtractorFactory` decoupled registry and factory for feature extractors.
- `intelligent_tracker/matching/__init__.py` (Created, 18 lines): Re-export facade with complete `__all__` registry.
- `intelligent_tracker/matching/types.py` (Created, 60 lines): `EntityIdentifiedEvent` and `SessionEntity` tracking identity dataclasses.
- `intelligent_tracker/matching/adaptive_memory.py` (Created, 102 lines): `apply_bounded_ema_update` with anchor drift guard and SQLite signature update helpers.
- `intelligent_tracker/matching/session_gallery.py` (Created, 151 lines): `SessionGalleryManager` automatic session identities, dropout re-linking, and exit telemetry.
- `intelligent_tracker/matching/gallery.py` (Created, 423 lines): `GalleryMatcher` class (10 methods) coordinating database gallery, cross-camera topology priors, active learning triage, and session tracking.
- `intelligent_tracker/matcher.py` (Modified, 21 lines): Facade re-exporting `GalleryMatcher`, `EntityIdentifiedEvent`, `SessionEntity`, `SessionGalleryManager`, `apply_bounded_ema_update`.
- `intelligent_tracker/reid.py` (Deleted, 555 lines): Superseded by `intelligent_tracker/reid/` package.

### 3. Verification & Testing
- **Modularity Audit**:
  - `python <skill_dir>/scripts/code_health_audit.py --path intelligent_tracker/reid intelligent_tracker/matching intelligent_tracker/matcher.py --show-methods`:
  - Result: 14/14 files within budget, `GalleryMatcher` class down from 543L to 10 methods (healthy target $\le 10$).
- **Contract & Regression Parity**:
  - `python <skill_dir>/scripts/contract_snapshot.py verify --path . --strict`:
  - Result: Tier 1 AST & DOM Invariant Parity: VERIFIED (Zero regressions, 0 discrepancies).
- **Targeted Test Suites**:
  - `tests/test_reid.py` (8/8 OK in 0.19s)
  - `tests/test_enrollment.py` (3/3 OK in 0.78s)
  - `tests/test_matcher.py` (7/7 OK in 0.02s)
  - `tests/test_occlusion_and_ema.py` (4/4 OK in 0.27s)
  - `tests/test_topology.py` (8/8 OK in 0.003s)
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 304 tests in 45.419s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## 2026-11-04: Refactor Monolith - Phase 5 (Sub-Phase 5.3): Camera Auto-Discovery & Source Diagnostics (intelligent_tracker/discovery/)

### 1. Root Cause & Architectural Triage
- **Monolith Deconstruction**:
  - `intelligent_tracker/discovery.py` was a 560-line God module combining multi-protocol camera auto-discovery: physical USB hardware indexing, ONVIF WS-Discovery UDP multicast probes, TCP port reachability checking, subnet IP candidate generation, concurrent RTSP LAN port scanning, vendor preset RTSP URL builders with credential encoding (Hikvision, Tapo, EZVIZ, Dahua, Generic), and live connection diagnostics with base64 JPEG snapshot extraction.
  - Several functions exceeded quantitative modularity limits: `test_camera_connection` (106 lines), `probe_onvif_devices` (79 lines), `build_preset_rtsp_url` (65 lines), and `discover_all_cameras` (50 lines).
  - Decomposed the monolith into a clean, SRP-compliant domain package (`intelligent_tracker/discovery/`) across 9 cohesive submodules with 0 critical breaches. All files are $\le 142$ lines (healthy budget $\le 350$ lines), and all functions are $\le 40$ lines.
- **Zero-Breaking-Import Facade**:
  - `intelligent_tracker/discovery/__init__.py` (47 lines) re-exports 100% of public dataclasses, probe functions, multicast constants, and vendor presets with complete backwards compatibility and explicit `__all__` registry.
  - Maintained zero broken imports across all callers (`tests/test_discovery.py`, `tests/test_vms_api.py`, `dashboard/routers/cameras.py`, `dashboard/routers/camera_diagnostics.py`).
- **Shutdown Deadlock Remediation**:
  - Resolved lock contention in `StreamManager.stop()` where `self._thread.join()` was invoked while holding `self._lock`, preventing the worker thread from acquiring `self._lock` during termination and causing a 0.6s join timeout. Moving `join()` outside `self._lock` reduced shutdown latency to 7ms.

### 2. Files Modified & Created
- `intelligent_tracker/discovery/__init__.py` (Created, 47 lines): Re-export facade with complete `__all__` registry.
- `intelligent_tracker/discovery/types.py` (Created, 28 lines): `DiscoveredCamera` dataclass representation and `to_dict()` serializer.
- `intelligent_tracker/discovery/usb.py` (Created, 47 lines): `find_physical_cameras` local hardware probing across DirectShow, V4L2, and AVFoundation.
- `intelligent_tracker/discovery/onvif.py` (Created, 138 lines): `WS_DISCOVERY_PROBE_XML`, `WS_DISCOVERY_MULTICAST_GROUP`, `WS_DISCOVERY_PORT`, `probe_onvif_devices`, `_create_multicast_socket`, `_parse_onvif_packet`, `_collect_onvif_responses`.
- `intelligent_tracker/discovery/network.py` (Created, 82 lines): `check_port_open`, `get_local_subnet_ips`, `_determine_local_ip`, `_generate_subnet_candidates`.
- `intelligent_tracker/discovery/rtsp.py` (Created, 57 lines): `discover_rtsp_devices` concurrent multi-threaded port scanner.
- `intelligent_tracker/discovery/presets.py` (Created, 123 lines): `build_preset_rtsp_url`, `_format_auth_prefix`, `_build_netloc`, `_build_vendor_path`, `CAMERA_PRESETS`.
- `intelligent_tracker/discovery/connection.py` (Created, 142 lines): `test_camera_connection`, `_test_synthetic_source`, `_check_network_reachability`, `_format_capture_open_error`, `_decode_snapshot`.
- `intelligent_tracker/discovery/scanner.py` (Created, 83 lines): `discover_all_cameras`, `_resolve_empty_fallbacks`.
- `intelligent_tracker/discovery.py` (Deleted, 560 lines): Superseded by `intelligent_tracker/discovery/` package.
- `dashboard/stream_manager.py` (Modified): Moved worker thread join out of `self._lock` in `stop()` to eliminate join timeout deadlock.

### 3. Verification & Testing
- **Modularity Audit**:
  - `python <skill_dir>/scripts/code_health_audit.py --path intelligent_tracker/discovery --show-methods`:
  - Result: 9/9 files OK (all $\le 142$ lines, healthy budget $\le 350$ lines), 0 Critical breaches, 0 God classes.
- **Contract & Regression Parity**:
  - `python <skill_dir>/scripts/contract_snapshot.py verify --path . --strict`:
  - Result: Tier 1 AST & DOM Invariant Parity: VERIFIED (Zero regressions, 0 discrepancies).
- **Targeted Discovery Tests**:
  - `tests/test_discovery.py` (11/11 OK in 0.43s)
  - `tests/test_vms_api.py` (6/6 OK in 10.8s)
  - `tests/test_camera_pool.py` (8/8 OK in 1.47s)
  - `tests/test_graceful_shutdown_perf.py` (7/7 OK in 0.68s)
  - `tests/test_tracker.py` (9/9 OK in 0.01s)
  - `tests/test_matcher.py` (7/7 OK in 0.03s)
  - `tests/test_reid.py` (8/8 OK in 0.50s)
  - `tests/test_video.py` (10/10 OK in 0.49s)
- **Full Test Suite**:
  - `python -m unittest discover tests`: Ran 304 tests in 55.512s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`: Clean build with **0 warnings**.
## [Sub-Phase 6.1] - 2026-11-04 - Application Entrypoint & CLI Subsystem Decomposition (`main.py` -> `intelligent_tracker/cli/`)

### 1. Summary of Changes
- **Monolith Deconstruction**:
  - `main.py` was a 710-line monolith housing a 511-line `main()` function and a 95-line `parse_args()` function combining CLI argument parsing, configuration loading, resolution parsing, subsystem wiring (detector, tracker, analytics, reid, alerting, writer), GUI window setup, mouse interaction callbacks, interactive keyboard dispatch, and clean shutdown summary printing.
  - Decomposed the monolith into a clean, SRP-compliant CLI package (`intelligent_tracker/cli/`) across 5 focused modules with 0 critical breaches.
  - `main.py` was reduced from 710 lines down to a clean 32-line bootstrap and re-export facade with 100% backwards compatibility.
- **CLI Architecture**:
  - `intelligent_tracker/cli/arguments.py` (171 lines): Argument parser construction with focused argument groups (`_add_detector_args`, `_add_reid_args`, `_add_pipeline_args`, `_add_runtime_args`), `load_config`, and `parse_resolution`.
  - `intelligent_tracker/cli/pipeline_builder.py` (292 lines): `PipelineContext` dataclass, configuration resolution, and modular builder functions (`_build_detector`, `_build_tracker`, `_build_analytics`, `_build_reid`, `_build_alerting`, `_build_writer`).
  - `intelligent_tracker/cli/display.py` (167 lines): `CliUiController` managing OpenCV HUD overlay rendering, mouse inspection callbacks, interactive keyboard dispatch, entity gallery enrollment, snapshot exports, and window lifecycle.
  - `intelligent_tracker/cli/runner.py` (234 lines): `CliAppRunner` coordinating video ingestion, inference, Re-ID alerts, MQTT telemetry publishing, FPS calculation, and clean resource teardown, plus legacy Matplotlib GUI fallback.
  - `intelligent_tracker/cli/__init__.py` (41 lines): Domain re-export facade with complete `__all__` registry.
- **Modernization & Invariants**:
  - Zero `__future__` imports, zero obsolete shims, all classes $\le 10$ methods, all functions $\le 33$ lines.

### 2. Files Modified & Created
- `intelligent_tracker/cli/__init__.py` (Created, 41 lines)
- `intelligent_tracker/cli/arguments.py` (Created, 171 lines)
- `intelligent_tracker/cli/pipeline_builder.py` (Created, 292 lines)
- `intelligent_tracker/cli/display.py` (Created, 167 lines)
- `intelligent_tracker/cli/runner.py` (Created, 234 lines)
- `main.py` (Modified, 710 -> 32 lines)

### 3. Verification & Testing
- **Modularity Audit**:
  - `code_health_audit.py --path main.py intelligent_tracker/cli --show-methods`:
  - Result: 6/6 files OK, 0 Critical breaches, all classes $\le 10$ methods, all functions $\le 33$ lines.
- **Contract & Regression Parity**:
  - `contract_snapshot.py verify --path . --strict`: Tier 1 AST & DOM Invariant Parity: VERIFIED (Zero regressions).
- **Execution Smoke Tests**:
  - `python main.py --help`: OK (Clean usage & option listings)
  - `python main.py --source synthetic --headless --frames 5`: OK (Processed 5 frames, clean shutdown)
- **Modernization Suite**:
  - `python -m unittest discover tests -p "test_modernization.py"`: 2/2 tests OK.
## [Phase 6 Complete] - 2026-11-04 - Application Entrypoint & Streaming Service Orchestration (`stream_manager.py` Decomposition)

### 1. Root Cause & Architectural Triage
- **Monolith Deconstruction**:
  - `dashboard/stream_manager.py` was a 748-line God module containing a 696-line `StreamManager` class with 32 items/methods, a 240-line `_worker_loop`, a 153-line `_init_subsystems`, and an 86-line `__init__`. It violated the Single Responsibility Principle by mixing configuration parsing, computer vision pipeline construction, background worker threading, self-healing leased subscriber eviction, frame overlays, spatial occupancy heatmap rendering, JPEG encoding, and click-to-tag Re-ID registration.
  - Decomposed the monolith into focused, SRP-compliant services in `dashboard/services/` with 0 critical breaches:
    1. `dashboard/services/pipeline_factory.py` (270 lines): `StreamPipelineFactory` and `StreamPipelineBundle` dataclass handling configuration loading, video source initialization, detector/tracker instantiation, spatial analytics zones and tripwires, Re-ID matcher, and event bus wiring.
    2. `dashboard/services/stream_media.py` (108 lines): `StreamMediaMixin` providing video frame rendering, overlay toggling (`set_overlays`/`get_overlays`), BEV minimap generation, accumulated heatmap encoding, telemetry snapshots, and interactive entity tagging delegation.
    3. `dashboard/services/stream_subscribers.py` (172 lines): Enhanced with `StreamSubscriberMixin` delegating viewer leases, TTL eviction, and WebSocket telemetry broadcasting to `StreamSubscriberRegistry`.
    4. `dashboard/services/stream_worker.py` (337 lines): `StreamWorker` executing the continuous frame ingestion, computer vision inference, spatial analytics, Re-ID matching, and telemetry distribution loop with pure module-level helpers (`_diagnose_source_error`, `_resize_frame_if_needed`, `_measure_fps`, `_extract_recent_alerts`, `_extract_track_telemetry`, `_build_zones_data`, `_build_tripwires_data`).
    5. `dashboard/stream_manager.py` (224 lines): Clean facade class inheriting from `StreamSubscriberMixin` and `StreamMediaMixin`, delegating pipeline initialization to `StreamPipelineFactory` and the background loop to `StreamWorker`. Method count reduced from 32 items down to 10 items (healthy target $\le 10$).
- **Zero-Breaking-API Invariant**:
  - Preserved 100% of public attributes and methods on `StreamManager` (`camera_id`, `name`, `db`, `video_source`, `detector`, `tracker`, `analytics`, `reid_extractor`, `gallery_matcher`, `rsac_manager`, `event_bus`, `overlays`, `subscriber_count`, `is_hibernating`, `is_running`, `width`, `height`, `start`, `stop`, `signal_stop`, `set_overlays`, `get_overlays`, `get_bev_minimap_jpeg`, `get_latest_frame_jpeg`, `get_latest_telemetry`, `get_heatmap_jpeg`, `toggle_heatmap`, `tag_entity`, etc.).
  - Preserved backward-compatible subscriber aliases (`self._subscribers`, `self._ws_subscribers`, `self._subscriber_lock`, `self._is_hibernating`).
- **Complete Phase 6 Milestones**:
  - Sub-Phase 6.1: `main.py` decomposed into `intelligent_tracker/cli/` (Arguments, Pipeline Builder, Display, Runner).
  - Sub-Phase 6.2: `dashboard/stream_manager.py` decomposed into `dashboard/services/` (Pipeline Factory, Stream Worker, Stream Media, Stream Subscribers).
  - All Phase 6 targets now satisfy the quantitative modularity budgets.

### 2. Files Modified & Created
- `dashboard/services/pipeline_factory.py` (Created, 270 lines): Subsystem builder and pipeline bundle.
- `dashboard/services/stream_media.py` (Created, 108 lines): Media export and overlay mixin.
- `dashboard/services/stream_worker.py` (Created, 337 lines): Background worker pipeline loop.
- `dashboard/services/stream_subscribers.py` (Modified, 172 lines): Added `StreamSubscriberMixin`.
- `dashboard/services/__init__.py` (Modified, 28 lines): Exported new services.
- `dashboard/stream_manager.py` (Modified, 224 lines): Clean coordinator facade.
- `intelligent_tracker/cli/pipeline_builder.py` (Modified, 291 lines): Minor formatting optimization to keep all functions $\le 40$ lines.

### 3. Verification & Testing
- **Modularity Audit**:
  - `code_health_audit.py --path main.py intelligent_tracker/cli dashboard/stream_manager.py dashboard/services/pipeline_factory.py dashboard/services/stream_media.py dashboard/services/stream_subscribers.py dashboard/services/stream_worker.py dashboard/services/__init__.py --show-methods`:
  - Result: 12/12 files OK, 0 Critical breaches, all classes $\le 10-11$ methods, all functions $\le 40$ lines.
- **Contract & Regression Parity**:
  - `contract_snapshot.py verify --path . --strict`: Tier 1 AST & DOM Invariant Parity: VERIFIED (Zero discrepancies).
- **Targeted Subsystem Tests**:
  - `tests/test_graceful_shutdown_perf.py` (7/7 OK in 0.63s)
  - `tests/test_hibernation.py` (6/6 OK in 1.88s)
  - `tests/test_camera_pool.py` (8/8 OK in 1.80s)
  - `tests/test_dashboard.py` (12/12 OK in 0.71s)
  - `tests/test_vms_api.py` (6/6 OK in 6.21s)
  - `tests/test_modernization.py` (2/2 OK in 0.89s)
- **Full Test Suite**:
  - Ran 304 tests in 41.2s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - Clean build with **0 warnings**.

---
## [Phase 7 Complete] - 2026-11-04 - Test Suite De-crufting, Parallel Tests & Warning Remediations

### 1. Root Cause & Architectural Triage
- **Overloaded Test Monoliths**:
  - `tests/test_core.py` was a 760-line test monolith containing `SpaceTestCase`, `WeakDictionaryTestCase`, `GroupTestCase`, `CompleteGroupTestCase`, and a 216-line `GroupEfficiencyTestCase` with a 207-line micro-benchmark method `test_compare`.
  - `tests/test_events.py` was a 720-line test monolith mixing event dataclass tests, base64 JPEG encoding/decoding, async worker pub/sub tests, HTTP echo server fixtures, Webhook delivery with HMAC signatures, Telegram bot command dispatchers, MQTT topic publishers, QuietHours schedules, AlertRuleEngine filters, and full pipeline integration.
- **Decomposition Architecture**:
  - Decomposed `tests/test_core.py` into focused, domain-aligned test modules:
    1. `tests/test_core_spaces.py` (198 lines): Space hierarchy, parenting constraints, circular reference prevention, and `WeakWatcherDictionary` / `WeakRefDictionary` lifecycle.
    2. `tests/test_core_groups.py` (212 lines): `Group` / `CompleteGroup` inclusion, hierarchy conflict resolution, thread-safe iteration under with-statement context, and space deletions.
    3. `tests/test_core_efficiency.py` (230 lines): Micro-benchmarks, retrieval scaling, discard scaling, and memory footprint comparisons for Group and CompleteGroup.
  - Decomposed `tests/test_events.py` into focused, domain-aligned test modules:
    1. `tests/events_helpers.py` (62 lines): Shared local HTTP echo test server fixture (`WebhookTestServerHandler`, `WebhookTestServer`).
    2. `tests/test_events_bus.py` (203 lines): Base and typed dataclasses, base64 frame/crop encoding, synchronous & async pub/sub worker dispatch, and subscriber error containment.
    3. `tests/test_events_dispatchers.py` (236 lines): `WebhookDispatcher` (HTTP POST, bearer auth, backoff retry, HMAC sha256 signature), `TelegramDispatcher` (formatting, cooldown, bot commands), and `MqttPublisher` (occupancy, events, sightings, LWT).
    4. `tests/test_events_rules.py` (172 lines): `QuietHours` overnight/daytime evaluation, `AlertRule` criteria matching, `AlertRuleEngine` snapshot generation, and full pipeline integration with `AnalyticsEngine` and capacity breach alerts.
  - All test files now strictly comply with the quantitative budget ($\le 236$ lines, well below the 350-line target).
- **Frontend Controller Polish**:
  - `dashboard/static/camera_manager.js` (371L -> 347 lines): Merged duplicate `resetForm` declarations, extracted `bindDiscoveryControls` and `buildCameraPayload`, eliminating redundant handlers.
  - `dashboard/static/app.js` (370L -> 348 lines): Compacted `showToast`, `escapeHtml`, and `handleHashRoute` mapping, eliminated redundant `window.App.switchCamera` assignment.
  - `dashboard/static/video_scrubber.js` (353L -> 352 lines): Extracted `bindPlaybackControls` and `updateScrubberLoadedTitle`, cleaned DOM lookup block, preserved `window.VideoScrubber.onTabEnter`/`onTabLeave` export contracts.

### 2. Files Modified & Created
- `tests/test_core_spaces.py` (Created, 198 lines)
- `tests/test_core_groups.py` (Created, 212 lines)
- `tests/test_core_efficiency.py` (Created, 230 lines)
- `tests/events_helpers.py` (Created, 62 lines)
- `tests/test_events_bus.py` (Created, 203 lines)
- `tests/test_events_dispatchers.py` (Created, 236 lines)
- `tests/test_events_rules.py` (Created, 172 lines)
- `tests/test_core.py` (Deleted, superseded 760L monolith)
- `tests/test_events.py` (Deleted, superseded 720L monolith)
- `dashboard/static/camera_manager.js` (Modified, 371 -> 347 lines)
- `dashboard/static/app.js` (Modified, 370 -> 348 lines)
- `dashboard/static/video_scrubber.js` (Modified, 353 -> 352 lines)
- `.refactor/plan.md` (Updated, Phase 7 status marked completed)

### 3. Verification & Testing
- **Modularity Audit**:
  - `code_health_audit.py --path dashboard/static/app.js dashboard/static/camera_manager.js dashboard/static/video_scrubber.js tests/test_core_spaces.py tests/test_core_groups.py tests/test_core_efficiency.py tests/events_helpers.py tests/test_events_bus.py tests/test_events_dispatchers.py tests/test_events_rules.py`:
  - Result: 10/10 files OK, 0 Critical breaches, all files $\le 352$ lines, all functions $\le 40$ lines.
- **Contract & Regression Parity**:
  - `contract_snapshot.py verify --path . --strict`: Tier 1 AST & DOM Invariant Parity: VERIFIED (Zero discrepancies).
- **Targeted Subsystem Tests**:
  - `tests/test_core_*.py` (17/17 OK in 1.70s)
  - `tests/test_events_*.py` (21/21 OK in 1.22s)
  - `tests/test_modernization.py` (2/2 OK in 0.88s)
  - `tests/test_refactor_contract.py` (3/3 OK in 0.01s)
- **Full Test Suite**:
  - Ran 306 tests in 39.5s — **OK (100% green, 0 failures, 0 errors)**.
- **Sphinx Documentation**:
  - Clean build with **0 warnings**.

## [Milestone 8] - 2026-10-26 - World Scenario Studio, Space Awareness & Ground Plane Homography

### 1. Objectives & Scope
- Deliver interactive in-browser Scenario Studio for polygonal zone drawing and directional tripwires with IN/OUT normal vectors.
- Implement 4-point ground plane perspective homography mapping camera contact points $(x+w/2, y+h)$ to metric top-down $(X, Y)$ coordinates.
- Render tactical 2D Bird's-Eye-View (BEV) top-down minimap canvas with metric grids, projected zones, and velocity vectors.
- Realize cross-camera topological space awareness (`Scene`, `Area`, `Line` domain abstractions) with transit time windows $[T_{min}, T_{max}]$ and Bayesian spatial prior boosting for Re-ID gallery matching.
- Implement Trajectory Journey Search reconstructing multi-camera chronological hops with dwell and transit durations, and one-click MP4 journey video compilation.
- Implement floating overlay control toolbar dynamically toggling bounding boxes, track IDs, dwell timers, velocity, zones, tripwires, heatmap, BEV minimap, and HUD status.
- Support dual persistence: declarative YAML (`configs/scenarios.yaml`) and relational SQLite tables (`spatial_zones`, `spatial_tripwires`, `spatial_transitions`, `homography_calibrations`).

### 2. Files Touched & Created
- **Core Intelligence & Spatial Analytics:**
  - `intelligent_tracker/homography.py` *(New)*: `GroundPlaneHomography` class with 4-point calibration (`cv2.getPerspectiveTransform`), forward/inverse perspective mapping, contact point $(x+w/2, y+h)$ tracking, polygon projection, 2D BEV minimap canvas rendering, and dictionary serialization.
  - `intelligent_tracker/topology.py` *(New)*: `SpatialTransitionLink`, `ActiveSpatialPrior`, and `CrossCameraTopology` realizing multi-camera transition paths, transit time window filtering, zone exit event handlers, and Bayesian prior Re-ID boosting.
