# Debug HUD Picker Overflow, Status Filter, Sort/Search, Drag & Related-Link Autocomplete Plan

> **Scope**: Standalone tooling plan targeting the `system-diagnostics` skill (`assets/hud_core.js`, `assets/hud_drawer.js`, `assets/hud_drawer_render.js`, `scripts/observation_store.py`) — decoupled from the `intelligent_tracker` application Master Roadmap.
> **Observations Covered**: `OBS-037`, `OBS-042`, `OBS-044`, `OBS-045`, `OBS-046`.

---

## Milestone 1: Debug HUD UX, Overflow & Sorting Fixes *(Active)*

- [ ] **assets/hud_core.js**: Wrap picked selector text inside `.fh-chip` in a `<span class="fh-chip-label">` with `min-width: 0; overflow: hidden; text-overflow: ellipsis;` and set `flex-shrink: 0` on the `x` remove button (and mirror in `assets/hud_drawer_render.js:32-34`) so long CSS selectors never clip the remove button (`OBS-044`).
- [ ] **assets/hud_core.js**: Add pointer-capture drag support on `[data-a="title"]` / card header of `#__frontier_hud__` `[data-a="card"]` (clamped within viewport bounds) so users can move the HUD away from elements they want to pick (`OBS-042`).
- [ ] **assets/hud_drawer.js**: Add `resolved`, `open`, `triaged`, and `in_progress` options to `<select data-da="filter">` (`line 254`) matching `observation_store.py:27-28`, and add a sort toggle (`ID asc/desc` vs `Recent`) + text search input filtering cards by ID/message/selector (`OBS-037`, `OBS-045`).
- [ ] **scripts/observation_store.py**: Preserve stable numeric ID ordering option in `list_observations()` and track `updated_at` separately from `last_seen` on metadata edits in `patch_observation()` (`lines 274, 299-300`) so saving an edit does not scramble card order (`OBS-045`).
- [ ] **assets/hud_drawer_render.js**: Populate a `<datalist>` attached to `[data-da="rel-input"]` (`lines 58-61`) with recent `OBS-NNN` IDs and truncated summaries (excluding self and already-linked IDs) (`OBS-046`).
- [ ] **tests/test_observation_hud.py**: Add regression tests covering `.fh-chip` remove-button visibility on 180-char selectors, `resolved` filter option, stable ID sort on edit, text search, draggable card positioning, and `rel-input` datalist suggestions.
- [ ] **Verifier**: `python -m unittest discover -s "<config_dir>/skills/system-diagnostics/tests" -p "test_observation*.py"`
