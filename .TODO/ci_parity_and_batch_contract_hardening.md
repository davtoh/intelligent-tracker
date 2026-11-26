# Follow-Up Plan: CI Parity & Batch Detector Contract Hardening

**Goal**: Replace the silent `max(0.95, ...)` confidence override in `intelligent_tracker/batch.py:54` with an explicit contract fix and add cross-platform CI-parity test coverage for POSIX `/tmp` crop paths, `MockDetector` batch/Re-ID flows, and bounded `MultiviewSession` async teardown.

---

## Scenario Combinations Matrix

| Scenario | Environment / Input | Expected Behavior | Verification |
|---|---|---|---|
| **Batch `MockDetector` confidence** | `VideoIndexer(..., detector_name="mock", detector_confidence=0.45)` | Preserves caller `conf_threshold` (`0.45`) without silent `max(0.95, ...)` clamp; tests needing deterministic high confidence pass explicit config/fixture | `tests/test_ci_parity_and_batch_contract.py` |
| **POSIX `/tmp` crop avatar URL** | `_to_avatar_url("/tmp/tmpXYZ/person_1.jpg")` on Windows or Linux | Normalizes to `/crops/person_1.jpg` while preserving `/crops/...`, `http(s)://...`, `data:...` | `tests/test_ci_parity_and_batch_contract.py` |
| **Python 3.11/3.12 async WS teardown** | `MultiviewSession` shutdown with slow client socket | Sets `_stopped = True` before awaiting bounded `asyncio.wait_for(..., timeout=1.0)` close/cancel | `tests/test_multiview_session.py` |

---

## Milestone 1: Remove `batch.py` Silent Confidence Clamp & Fix Caller/Test Contract *(Active Execution Target)*

- [ ] **intelligent_tracker/batch.py**: Inspect all callers of `_create_batch_detector` and `MockDetector(..., confidence=...)` in `tests/` (`git grep -n "_create_batch_detector\|MockDetector" tests/ intelligent_tracker/`), then remove the `max(0.95, ...)` silent clamp on line 54 so `det_kwargs["confidence"] = conf_threshold` honors caller configuration.
- [ ] **tests/test_step5_e2e_closed_loop_ecosystem.py** *(or whichever CI test triggered the clamp)*: Pass explicit confidence or seed deterministic mock detections cleanly at the test boundary rather than mutating production detector config globally.
- [ ] **tests/test_ci_parity_and_batch_contract.py**: Add unit tests verifying `_create_batch_detector("mock", 0.45, None)` preserves `0.45` and exercises `VideoIndexer` end-to-end under `MockDetector` without local ONNX weights.
- [ ] **Verification**: Run `python -m unittest tests/test_ci_parity_and_batch_contract.py tests/test_step5_e2e_closed_loop_ecosystem.py tests/test_detectors.py` and `diagnose.py audit --path intelligent_tracker/batch.py tests/test_ci_parity_and_batch_contract.py`.

## Milestone 2: Cross-Platform POSIX `/tmp` & Async CI Parity Tests *(Deferred to Next Turn / Milestone)*

- [ ] **tests/test_ci_parity_and_batch_contract.py**: Add explicit POSIX path tests for `dashboard.services.entity_tagger._to_avatar_url` (`/tmp/crops/abc.jpg`, `C:\crops\abc.jpg`, `/crops/abc.jpg`, `https://...`, `data:...`) and `roi_recognition_helpers.record_roi_side_effects` avatar propagation.
- [ ] **tests/test_multiview_session.py**: Verify slow/hanging websocket close completes within bounded `1.0s` timeout without hanging event-loop teardown.
- [ ] **Verification**: Run `python -m unittest tests/test_ci_parity_and_batch_contract.py tests/test_multiview_session.py tests/test_step3_tracking_hysteresis_and_multitag.py tests/test_step1_reid_sightings_and_locks.py`.
