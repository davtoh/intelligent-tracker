---
trigger: model_decision
description: Apply when editing camera source selection, pipeline overrides (where camera index 0 may be passed), CameraConfigStore, or TrackerDB signature queries.
---

# Pipeline, Camera Config & DB Invariants

- **Camera Index `0` Falsy Trap**: Never use truthy `or` fallbacks for camera/source overrides (e.g., `source_override or default`), because integer webcam index `0` evaluates to `False` in Python. Always use explicit `is not None` checks (`source_override if source_override is not None else ...`).
- **`CameraConfigStore` Healing & Budget**:
  - Persist healed camera configs in `load_cameras()` only when `configs_loaded` is `True` so seeded defaults do not trigger redundant disk writes.
  - Keep `dashboard/services/camera_config_store.py` strictly under 180 lines as enforced by `tests/test_dashboard_di.py`.
- **`TrackerDB` Signature API**: `TrackerDB` exposes `get_signatures()` (not `get_all_signatures()`) and returns deserialized numpy embeddings directly.
- **Verification**: Check existing strict fallback tests (`tests/test_pipeline_config.py`) when splitting synthetic vs live-source detector error handling, and run `tests/test_dashboard_di.py` plus `python -m unittest discover tests` after modifying `CameraConfigStore` or DI services.
