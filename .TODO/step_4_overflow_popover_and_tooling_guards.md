# Step 4: Layout Overflow Containment, Status Popover Cleanup & Long-Fixture Tooling Guards

> **Parent Master Roadmap**: `.TODO/runtime_ux_and_reid_parity_master_roadmap.md` (`--parent runtime_ux_and_reid_parity_master_roadmap --milestone 4`)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–21`), `docs/architecture/CURRENT_ARCHITECTURE.md` (`OBS-011`, `OBS-012`, `OBS-013`, `OBS-015`)
> **Goal**: Fix flex/select overflow regressions on `#videos .upload-status-hint` (`OBS-011`), `#analytics #analytics-source-select` (`OBS-013`), and `#review .review-card` (`OBS-015`), clear `.truncate-trigger` / `data-full-text` in `#connection-status-text` on camera/mode changes (`OBS-012`), and add long-filename CDP fixtures + `system-diagnostics` JS AST/lexer guard rules.

---

## Public Surface, Modularity Budgets & Contracts

### 1. Modularity Budget Guardrails
- Global soft ceiling `<= 350L`/file (hard `< 500L`), `<= 12` methods/class, `<= 40L`/function, zero `!important` in CSS.
- **Tight-Cap Files**: `dashboard/static/css/scrubber.css` (`349L`), `dashboard/static/css/views.css` (`341L`), `dashboard/static/app.js` (`336L`), `dashboard/static/js/analytics_view.js` (`332L`), and `system-diagnostics/scripts/shadow_prober.py` (`349L`) must all remain `< 350L`.

### 2. Scenario Combinations Matrix
| Scenario | Input / Trigger | Expected Outcome | Verification |
| :--- | :--- | :--- | :--- |
| **`#videos` Upload Status Hint (`OBS-011`)** | Upload or display 70+ char filename in `#video-upload-status` | `.sidebar-column`, `.video-upload-panel`, and `.upload-status-hint` wrap cleanly within panel bounds (`overflow-wrap: anywhere`) | `spa_nine_tab_cdp_probe`, `test_step4_overflow_popover_and_guards.py` |
| **`#analytics` Source Select (`OBS-013`)** | Populate `#analytics-source-select` with long video/camera name | `.analytics-grid` uses `minmax(0, 1fr)`, `#analytics-source-select` caps width with ellipsis + `title` tooltip, native popup shows full option text | `spa_nine_tab_cdp_probe`, `test_step4_overflow_popover_and_guards.py` |
| **`#review` Card Overflow (`OBS-015`)** | Render review card with `video:<long_filename>` and long title | `.review-queue-grid`, `.review-card`, `.review-meta`, `.review-title`, `.review-source-pill` contain children inside card bounds | `spa_nine_tab_cdp_probe`, `test_step4_overflow_popover_and_guards.py` |
| **Status Popover Cleanup (`OBS-012`)** | Switch from long camera/video to short `cam_01` or `simulation` | `TextTruncationManager.clear()` removes `.truncate-trigger`, `data-full-text`, `aria-*`, and hides active popover if bound | `test_step4_overflow_popover_and_guards.py`, `spa_nine_tab_cdp_probe` |
| **JS Guard Rules (`diagnose.py scan`)** | Scan JS fixtures + `dashboard/static/` | `JS_RAF_DPR_RESIZE`, `JS_HOT_EVENT_LOCALSTORAGE`, `JS_PRIVATE_SWITCH_TAB_BINDING` flag bad patterns and pass cleanly on workspace | `test_js_guard_rules.py`, `diagnose.py scan --strict` |

---

## Milestone 1: Layout Overflow Containment, Status Popover Cleanup & Long-Fixture Tooling Guards *(Active)*

- [x] **dashboard/static/css/sidebar.css** & **dashboard/static/css/scrubber.css**: Add `min-width: 0` on `.sidebar-column`, `min-width: 0; overflow: hidden;` on `.video-upload-panel`, and `min-width: 0; max-width: 100%; overflow-wrap: anywhere; word-break: break-word;` on `.upload-status-hint`, keeping `scrubber.css <= 349L` (`OBS-011`).
- [x] **dashboard/static/css/views.css**, **dashboard/static/css/analytics_alerts.css**, & **dashboard/static/js/analytics_view.js**: Update `.analytics-grid` to `minmax(0, 1fr) minmax(0, 1fr)`, add `min-width: 0` on `.chart-card, .heatmap-card` and `.analytics-flow-controls`, cap `#analytics-source-select, #analytics-zone-select` to `max-width: min(100%, 240px)` with ellipsis, and sync `sel.title` on load/change (`OBS-013`).
- [x] **dashboard/static/css/review.css**: Clamp `.review-queue-grid` via `minmax(min(100%, 320px), 1fr)`, add `min-width: 0; overflow: hidden;` on `.review-card` and `.review-meta`, `overflow-wrap: anywhere` on `.review-title`/`.review-candidate-match`/`.review-timestamp`, ellipsis containment on `.review-source-pill, .review-bbox-badge`, and wrapping on `.review-seek-row`/`.review-resolved-row` (`OBS-015`).
- [x] **dashboard/static/js/text_truncation_manager.js**, **dashboard/static/js/app_ui_helpers.js**, **dashboard/static/js/telemetry.js**, & **dashboard/static/app.js**: Add `TextTruncationManager.clear(element)`, `AppUIHelpers.clearTruncationState(el)`, clear stale `.truncate-trigger` / `data-full-text` on `#connection-status-text` in `updateWsStatus()`, `TelemetryGateway.updateConnectionStatus()`, and `switchCamera()` (`OBS-012`).
- [x] **.diagnostics/probes/spa_nine_tab_cdp_probe.py** & **.diagnostics/probes/spa_nine_tab_sweep.js**: Seed a 71-char video filename + `review_item` fixture and assert `uploadHintContained`, `analyticsSelectContained`, `reviewCardContained`, and `connStatusPopoverCleared`.
- [x] **C:/Users/User/.gemini/config/skills/system-diagnostics/scripts/js_guard_rules.py**, **shadow_prober.py**, & **tests/test_js_guard_rules.py**: Add `JS_RAF_DPR_RESIZE`, `JS_HOT_EVENT_LOCALSTORAGE`, and `JS_PRIVATE_SWITCH_TAB_BINDING` rules, wire into `audit_polyglot_lexer()` (keeping `shadow_prober.py <= 350L`), and verify with unit tests.
- [x] **tests/test_step4_overflow_popover_and_guards.py**: Add Node VM and static CSS/HTML contract tests for `TextTruncationManager.clear()`, `updateWsStatus()`, `updateConnectionStatus()`, `switchCamera()`, and overflow containment rules.
- [x] **Verifier & Sign-Off**: Run modularity audit, `diagnose.py tests`, `test_js_guard_rules.py` + `test_shadow_prober.py`, `spa_nine_tab_cdp_probe`, `surface --verify`, `scan --path dashboard intelligent_tracker --strict`, full `unittest discover tests`, Sphinx `-W`, fresh reviewer check, resolve `OBS-001`..`OBS-019` (except `OBS-020`..`022`), `diagnose.py changelog add`, `plan_engine.py verify/advance/digest/retrospective`.
