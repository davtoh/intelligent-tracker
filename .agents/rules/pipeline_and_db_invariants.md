---
trigger: model_decision
description: Apply when editing camera source selection or pipeline overrides where camera index 0 may be passed.
---

# Pipeline Camera Index `0` Invariant

- **Camera Index `0` Falsy Trap**: Never use truthy `or` fallbacks for camera/source overrides (e.g., `source_override or default`), because integer webcam index `0` evaluates to `False` in Python. Always use explicit `is not None` checks (`source_override if source_override is not None else ...`).
