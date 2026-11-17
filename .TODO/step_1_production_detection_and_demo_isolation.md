# Step 1 Implementation Plan: Production Detection Defaults, Demo Mode Isolation & Tagger Decomposition

> **Parent Master Plan**: `.TODO/live_video_studio_master_roadmap.md` (Step 1)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Subsequent Turns*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py audit`)

Measured against workspace baseline before edits:
- `intelligent_tracker/pipeline/config.py`: 274 lines (OK `< 350L`). Currently defaults `detector_fallback_mock: bool = False` on the dataclass, but `StreamPipelineFactory.build()` in `dashboard/services/pipeline_factory.py:86` passes `detector_fallback_mock=True` unconditionally for all cameras, and `configs/alert_demo.yaml:12` sets `detector.model: mock`.
- `intelligent_tracker/pipeline/bundle.py`: 344 lines (6 lines below the `350L` soft warning ceiling). `build_detector()` (lines 118–146) silently catches any `Exception` and returns `DetectorFactory.create("mock")`, causing `MockDetector` (`label="mock_person"`) to draw a synthetic sliding `60x120` box on real USB, RTSP, and video-file streams.
- `dashboard/services/camera_config_store.py`: 167 lines (OK `< 350L`). Loads `configs/cameras.json` without healing legacy `"detector": "mock"` entries on non-synthetic feeds (`vid_*`, `usb_*`).
- `dashboard/services/entity_tagger.py`: 136 lines, **DEFECT FLAGGED**: `tag_entity()` at line 26 is **110 lines** (`> 40L` function budget ceiling), falls back to a blind center-50% crop (`[w // 4, h // 4, w // 2, h // 2]`) when no bbox/track matches, and falls back to `np.random.randn(128)` random noise when `reid_extractor` is `None`.
- `dashboard/static/js/camera_ai_config.js`: 234 lines (OK `< 350L`). Allows selecting `mock` detector on any physical/RTSP camera without warning or source gating.
- `dashboard/static/camera_manager.js`: 366 lines (`WARN >= 350L`). Initializes `focusedCameraId = 'cam_01'` even when `cam_01` does not exist in `activeCameras`.

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- `PipelineConfig.from_dict()` continues honoring explicit `detector_fallback_mock=True` when passed by unit tests or when `source` / `cam_type` is synthetic (`"synthetic"`, `"mock"`), while `StreamPipelineFactory.build()` only enables `detector_fallback_mock` for synthetic sources.
- `PipelineBundle` preserves all existing attributes and adds `detector_status: str = "ready"` (`"ready"` | `"simulation"` | `"unavailable"`) and `detector_error: str | None = None`.
- `CameraConfigStore.load_cameras()` preserves its `(configs, seeded)` return tuple while healing non-synthetic `"detector": "mock"` entries to `"yolov8"` (when `config_file` is the live `configs/cameras.json` or via `heal_non_synthetic_mock_cameras()`).
- `EntityTaggerService.tag_entity()` preserves its exact parameter signature and return dictionary keys (`entity_id`, `name`, `category`, `signature_id`, `crop_path`).

### Modularity Guardrails
- `intelligent_tracker/pipeline/bundle.py` MUST remain `< 350` lines (extract detector resolution helper to `intelligent_tracker/pipeline/_detector_setup.py`).
- Every function in `dashboard/services/entity_tagger.py` MUST be `<= 35` lines (hard audit ceiling `<= 40` lines).
- Do not add lines to `dashboard/static/camera_manager.js` (366L) or `dashboard/static/app.js` (355L); place UI helper logic in `dashboard/static/js/camera_ai_config.js` (`< 280L`).

---

## 3. Phased Implementation Milestones

### Milestone 1: Pipeline Detector Guardrails & `_detector_setup.py` Extraction *(Active Execution Target)*
- [x] **intelligent_tracker/pipeline/config.py**: Add `is_synthetic_source(source: Any, cam_type: str | None = None) -> bool` helper and default `reid_model` to `"color"` when `db_path` is present and `reid.model` is omitted so live streams always have a deterministic visual feature extractor.
- [x] **intelligent_tracker/pipeline/_detector_setup.py**: Create focused helper module (`< 90L`, functions `<= 30L`) implementing `build_detector_with_status(config: PipelineConfig, *, raise_on_error: bool | None = None) -> tuple[Any, str, str | None]` that returns `(detector, status, error_msg)` — returning `status="simulation"` when `mock` is explicitly requested on a synthetic source, `status="ready"` when a real detector loads, and a no-op `EmptyDetector` (`detect() -> []`, `status="unavailable"`) instead of `MockDetector("mock_person")` when a real detector fails on a non-synthetic source and `detector_fallback_mock=False`.
- [x] **intelligent_tracker/pipeline/bundle.py**: Delegate `build_detector()` to `_detector_setup.py` and store `detector_status` and `detector_error` on `PipelineBundle`, keeping `bundle.py` `< 340` lines.
- [x] **dashboard/services/pipeline_factory.py**: Update `StreamPipelineFactory.build()` to set `detector_fallback_mock=is_synthetic_source(source_override or data.get("video", {}).get("source"), data.get("type"))` instead of unconditional `True`.
- [x] **tests/test_step1_pipeline_detector_guard.py**: Add isolated unit tests verifying `is_synthetic_source`, `EmptyDetector` vs `MockDetector` fallback branches (`if/elif/else`), `detector_status` (`ready`, `simulation`, `unavailable`), and `bundle.py < 350L` compliance.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 1 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step1_pipeline_detector_guard.py"
```

---

### Milestone 2: `CameraConfigStore` Legacy Mock Healing, `cameras.json` Cleanup & Telemetry Status *(Deferred to Next Turn)*
- [x] **dashboard/services/camera_config_store.py**: Add `heal_non_synthetic_mock_cameras(configs: dict[str, dict[str, Any]]) -> bool` that upgrades any camera entry whose `source` and `type` are non-synthetic (`usb`, `rtsp`, `hikvision` with non-synthetic source, `video_file`) from `"detector": "mock"` to `"yolov8"`, and removes stale `docker_notice` synthetic duplicates.
- [x] **configs/cameras.json**: Update persisted non-synthetic camera entries (`vid_*`, `usb_*`) from `"detector": "mock"` to `"detector": "yolov8"` and keep `"synthetic_01"` (`type: "synthetic"`, `detector: "mock"`) as the single explicit simulation channel.
- [x] **dashboard/services/stream_worker.py**: Include `"detector_model"` and `"detector_status"` in `_build_telemetry()` so the frontend HUD can display whether detection is `active`, `simulation`, or `unavailable`.
- [x] **tests/test_step1_camera_config_healing.py**: Add isolated unit tests (using `tempfile.TemporaryDirectory`) verifying `heal_non_synthetic_mock_cameras()` across `video_file`, `usb`, `rtsp`, and `synthetic` entries and verifying telemetry `detector_status` fields.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 2 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step1_camera_config_healing.py"
```

---

### Milestone 3: `EntityTaggerService` Decomposition (`<= 35L` Functions) & Deterministic Re-ID Embeddings *(Deferred to Next Turn)*
- [x] **dashboard/services/entity_tagger.py**: Decompose the 110-line `tag_entity()` method into focused `<= 30L` static helpers (`_resolve_target_bbox`, `_extract_bounded_crop`, `_compute_deterministic_embedding`, `_upsert_entity_and_signature`, `_update_live_track_identity`), raising a clear `ValueError("Select or draw a bounding box on the video before tagging")` when neither `bbox` nor a valid live `track_id` is found (eliminating the blind center-50% screen crop) and computing a deterministic HSV/spatial signature via `ReIDExtractorFactory.create("color")` when `reid_extractor` is `None` (eliminating `np.random.randn(128)` noise vectors).
- [x] **tests/test_step1_entity_tagger_refactor.py**: Add unit tests exercising all branches of `EntityTaggerService.tag_entity` (explicit `bbox`, active `track_id`, missing bbox/track `ValueError`, deterministic embedding repeatability across identical crops, and `diagnose.py audit` zero-defect check on `entity_tagger.py`).
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 3 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step1_entity_tagger_refactor.py"
```

---

### Milestone 4: Frontend Demo Simulation Gating, Initial Camera Focus Sync & Step 1 Sign-Off *(Deferred to Next Turn)*
- [x] **dashboard/static/js/camera_ai_config.js**: Label `mock` in `#cam-detector-select` as `🧪 Synthetic Mock (Demo Simulation Only)`, add a change listener that warns/switches `#cam-detector-select` to `yolov8` when a non-synthetic source is entered (or sets source to `synthetic` when Demo Simulation is explicitly chosen), and expose `resolveInitialCameraId(activeCameras, currentId)` to auto-select the first available camera when `cam_01` is not in `activeCameras`.
- [x] **dashboard/static/camera_manager.js**: Call `window.CameraAIConfig?.resolveInitialCameraId` inside `refreshCameras()` (1-line delegation keeping `camera_manager.js` line count unchanged or lower) so `#live` immediately attaches WebSocket telemetry and tagging to the actual first active camera on load.
- [x] **tests/test_step1_demo_mode_ui.py**: Add Node VM / unit tests verifying `CameraAIConfig.resolveInitialCameraId` and Demo Simulation detector/source synchronization plus full Step 1 regression verification.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 4 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step1_*.py"
```

---

## 4. Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Verify Milestone 1 (Detector Guard & `_detector_setup.py`)** | Headless unit suite | `test_step1_pipeline_detector_guard.py` | `python -m unittest discover -s tests -p "test_step1_pipeline_detector_guard.py"` |
| **Verify Milestone 2 (Camera Config Healing & Telemetry)** | Headless unit suite | `test_step1_camera_config_healing.py` | `python -m unittest discover -s tests -p "test_step1_camera_config_healing.py"` |
| **Verify Milestone 3 (`EntityTaggerService` <=40L Refactor)** | Headless unit suite | `test_step1_entity_tagger_refactor.py` | `python -m unittest discover -s tests -p "test_step1_entity_tagger_refactor.py"` |
| **Verify Milestone 4 (Demo UI Gating & Full Step 1)** | Headless unit suite | `test_step1_*.py` | `python -m unittest discover -s tests -p "test_step1_*.py"` |
| **Static Modularity Audit on All Step 1 Files** | AST Auditor | `--max-lines 350 --max-fn-lines 40` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/pipeline/config.py intelligent_tracker/pipeline/_detector_setup.py intelligent_tracker/pipeline/bundle.py dashboard/services/camera_config_store.py dashboard/services/entity_tagger.py dashboard/static/js/camera_ai_config.py --max-lines 350 --max-fn-lines 40` |
