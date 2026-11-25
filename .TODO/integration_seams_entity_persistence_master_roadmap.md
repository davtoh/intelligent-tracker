# Integration Seams, Entity Persistence & Studio UX Master Roadmap

> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–20`, Layers 1–5) & `docs/architecture/CURRENT_ARCHITECTURE.md` (branch `feature/reid-and-traceability-unification` at commit `49e508b`; `1,077` unittest baseline: `1,075` passed, `1` failed, `1` error).
> **How to use this document**: Execute one Step at a time via child plans linked in `.frontier/` (`--parent integration_seams_entity_persistence_master_roadmap --milestone <N>`). Only Step 1 is detailed into a child plan upfront; Steps 2–4 are deferred and planned one step at a time. Every Step enforces modularity budgets (`<= 350L` soft / `< 500L` hard, `<= 12` methods/class, `<= 40L`/fn, routes `<= 25L`) and a mandatory **Review Gate** (a fresh reviewer separate from the author inspects the diff and verify output before advancing).
> **Decision Basis (`/grill-me`, 13/13 decisions locked)**:
> 1. **Sequencing (Q1, Q13)**: Step 1 = P0 integration seams (`BUG-10`..`BUG-16`) + high-visibility P1/P2 fixes (`BUG-17`..`BUG-21`, `BUG-27`..`BUG-29`, detector panel, alerts checkboxes) + seam-level probes/tooling across 3 milestones (`Backend -> Frontend -> Tooling`); Step 2 = `SourceRef` + `ActiveSourceContext`; Step 3 = SORT/hysteresis persistence + multi-box tagging + Learned Classes; Step 4 = Reversible review + Studio/Analytics/Alerts UX.
> 2. **Re-ID Unification (Q2, `ADR-13`)**: Single canonical `ReidProfile` SSOT (`DualModel`) resolved in one place; YAML `reid.model` becomes advisory with loud boot warnings + `GET /api/system/gallery-health` + idempotent startup re-embed of mismatched DB vectors from stored crops/avatars.
> 3. **Detector Control & Replay Signature (Q3, `ADR-13`)**: Deep-merge per-camera config over `configs/default.yaml` (preserving `classes`, explicit `null` clears), add per-camera detector panel (COCO multi-select, confidence, `agnostic_nms` toggle default ON), and run live inference on `#live` video cameras unless a cached `video_runs` row matches the active detector signature.
> 4. **SQLite Alert SSOT (Q4, `ADR-14`)**: `EventBus` persists through to SQLite first and streams new IDs only; `/events` reads SQLite strictly; add row checkboxes + `"Select all matching"` for bulk ack/delete/export.
> 5. **Cross-Page `SourceRef` & `ActiveSourceContext` (Q5, Q10, `ADR-15`)**: Canonical `SourceRef` serialized into URL hash params via `App.navigate(tab, sourceRef)` (`#live?camera=...`, `#studio?camera=...&zone=...`, `#timeline?source=...&from=...&to=...`), global `ActiveSourceContext` selector across `#live`/`#analytics`/`#studio`/Enrollment, Pause/Resume `/freeze_frame` in Enrollment & `#studio`, and `MediaEmptyState` on missing sources.
> 6. **Sightings Provenance (Q6, `ADR-16`)**: `PRAGMA user_version` migration adding `sightings.camera_id` + `run_id`, seed sightings with crops on enrollment/active-learning, throttled backfill on relabel, and complete cameras + videos listing in `#timeline` Source filter.
> 7. **Tracking & Tagging Persistence (Q7, Q8, Q9, `ADRs 17–18`)**: Default `sort` + ByteTrack 2-stage association, `K=3` (`>= 0.65`) identity hysteresis lock, entity name/avatar boxes, multi-box track picker strip + Quick-Tag batch queue inside `#modal-tag-entity`, and exemplar Learned Classes + `Classes & Badges` page.
> 8. **Reversible Review & Tooling Gate (Q11, Q12, `ADRs 19–20`)**: `review_decisions` audit trail + Undo/`"Correct..."` + recurring unknowns + timeline `"Report wrong"`, shared `system-diagnostics` rules (`INFRA_UNAVAILABLE`, empty-sweep rejection, `data:image` decode, flex matrix, silent-skip scan, fetch parity), and workspace seam probes gating `plan_engine verify`.

---

## Step 1: P0 Integration Seams, High-Visibility Fixes & Seam-Level Probe Hardening
- [x] **Child Plan**: `.TODO/step_1_p0_integration_seams_and_probe_hardening.md` (`--parent integration_seams_entity_persistence_master_roadmap --milestone 1`).
- [x] **Goal**: Eliminate `BUG-10`..`BUG-21` and `BUG-27`..`BUG-29` at their cross-layer integration seams (Re-ID dimension parity, deep-merged per-camera detector control + replay signature match, SQLite-SSOT alerts + checkboxes, `App.navigate` deep links + `switchCamera` sync, Studio drag-to-`PUT` geometry edits, video-enrollment sightings provenance, modal grid ergonomics, standby SVG, connection pill) and upgrade `system-diagnostics` + workspace probes so `INFRA_UNAVAILABLE` and seam regressions are caught automatically.
- [x] **Verifier**:
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step1_seams_backend.py tests/test_step1_seams_frontend.py`
  - [x] `python -m unittest discover -s "<config_dir>/skills/system-diagnostics/tests" -p "test_*.py"`
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run effective_config_probe` (and `deep_link_navigation_probe`, `studio_drag_put_probe`, `alerts_store_probe`, `sightings_provenance_probe`, `spa_nine_tab_cdp_probe` — all passing outright, never `INFRA_UNAVAILABLE`)
  - [x] `MPLBACKEND=Agg python -m unittest discover tests; python -m sphinx -W --keep-going documentation/ documentation/_build/html/`
- [x] **Review Gate**: Fresh reviewer inspects diff, `diagnose.py audit --path <modified_files>`, and probe/test output before marking Step 1 complete.

---

## Step 2: Unified `SourceRef` Provenance, `ActiveSourceContext` & Media Freeze Controls *(Deferred to Next Turn / Milestone)*
- [ ] **Goal**: Extend `SourceRef` provenance uniformly across `sightings`, `world_timeline_events`, `/api/journey/*` hops (`track_id`), `/analytics/flows` & heatmap cells (media references), and `review_queue` (`run_id`); expose unified `ActiveSourceContext` source selectors across `#live`, `#analytics`, `#studio`, and Enrollment (with Pause/Resume `/freeze_frame` in Enrollment & `#studio`), Live/Studio deep-links on `#journey` & `#review`, and `MediaEmptyState` / `onerror` fallbacks (`journey_search.js`).
- [ ] **Target Scope**:
  - Add `track_id` to `JourneyHop`, media refs to `/analytics/flows` & heatmap JSON cells, `run_id` to `review_queue` writes (`_gallery_matching.py`), and explicit unavailable-source `MediaEmptyState` rendering on broken deep links.
  - Wire shared `ActiveSourceContext` (`localStorage` + URL hash pin override) into `#analytics` (`analytics.html`), `#studio`, and `#modal-universal-enrollment`, adding `/freeze_frame` Pause/Resume toggles for camera previews in Enrollment & `#studio` (`BUG-21`, `BUG-26`, `BUG-30`, `ADRs 15–16`).
- [ ] **Verifier**: `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step2_sourceref_and_context.py; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run deep_link_navigation_probe` (plus `spa_nine_tab_cdp_probe` non-INFRA pass).
- [ ] **Review Gate**: Fresh reviewer verifies `SourceRef` round-trips, modularity budgets (`<= 350L`/file, `<= 12` methods/class, `<= 40L`/fn), and zero `INFRA_UNAVAILABLE` probes before advancing.

---

## Step 3: SORT + ByteTrack Persistence, Multi-Box Tag Queue & Learned Classes *(Deferred to Next Turn / Milestone)*
- [ ] **Goal**: Stabilize per-frame tracking and entity identity via `sort` + ByteTrack two-stage association and hysteresis locking (`K=3` matches `>= 0.65`, `BUG-23`), render entity names/avatars on boxes, preserve person+bag ownership classes, support multi-box selection & Quick-Tag queues inside `#modal-tag-entity` (`BUG-22`), and launch exemplar-based Learned Classes + `Classes & Badges` management (`ADR-17`, `ADR-18`).
- [ ] **Target Scope**:
  - Default tracker to `sort` with ByteTrack 2-stage low-confidence association, per-camera tuning, and hysteresis identity binding so detector dropouts/class flips reinforce rather than replace `WorldEntity` bindings (`BUG-23`).
  - Return all overlapping tracks on canvas hit-test and queue Quick-Tag boxes in a reusable track picker strip inside `#modal-tag-entity` without dropping untagged tracks on submit (`BUG-22`).
  - Implement exemplar-based Learned Classes (ROI crop prototypes, per-camera COCO suppression/relabel) and a `Classes & Badges` management view unifying COCO classes, learned classes, and Semantic Category badges with cosine collision checks (`ADR-18`; YOLO-World remains deferred to a future SPIKE).
- [ ] **Verifier**: `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step3_tracking_hysteresis_and_multitag.py tests/test_step3_learned_classes.py; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run replay_pipeline_probe; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run spa_nine_tab_cdp_probe`.
- [ ] **Review Gate**: Fresh reviewer verifies tracker stability metrics, multi-box queue persistence, modularity budgets, and probe outputs before advancing.

---

## Step 4: Reversible Review Audit & Studio / Analytics / Alerts UX *(Deferred to Next Turn / Milestone)*
- [ ] **Goal**: Make Active Learning review decisions reversible via `review_decisions` audit trails (`Undo` + `"Correct..."`) while queueing recurring unknown tracks and timeline false positives (`BUG-24`, `ADR-19`), and close remaining UX parity gaps in `#studio`, `#journey`, `#analytics`, and `#alerts` (`BUG-25`).
- [ ] **Target Scope**:
  - Persist prior state in `review_decisions` on confirm/dismiss/reassign; add session Undo and `"Correct..."` (`#modal-tag-entity` Known state) reverting embeddings/negative exemplars and relabeling runs/sightings; queue recurring unknowns (`sim < 0.45`, seen `>= N s`) and timeline `"Report wrong"` items (`BUG-24`).
  - Add zoom/fit/pan and dedicated view toggle to `WorldTacticalMinimap`, draw saved 4-point BEV calibration quads on `#studio` feed (toggle all/selected), and reuse `#live`/`#video` canvas overlays (`BUG-25`).
  - Add `#journey` empty-prefix entity suggestions, `#analytics` flow filters/pagination, and `#alerts` canvas overlay reuse (`ADR-09`, `ADR-12`).
- [ ] **Verifier**: `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step4_reversible_review.py tests/test_step4_studio_ux_and_minimap.py; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker dashboard scripts; MPLBACKEND=Agg python -m unittest discover tests; python -m sphinx -W --keep-going documentation/ documentation/_build/html/`.
- [ ] **Review Gate**: Fresh reviewer validates non-mocked branch diff, all probes non-INFRA green, Sphinx `-W`, and `diagnose.py scan --strict` before closing roadmap.
