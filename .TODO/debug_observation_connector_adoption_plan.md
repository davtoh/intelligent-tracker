# Adoption Plan: Debug Observation Connector in `intelligent-tracker` (the app side of the contract)

> **Purpose:** this file is shipped into `davtoh/intelligent-tracker` (PR #13, `.TODO/debug_observation_connector_adoption_plan.md`) so that project implements **its half** of the debug observation contract owned by the `antigravity-skills` repo (`system-diagnostics` skill). It is self-contained: the wire contract is copied below.
> **Status (updated 2026-11-26):** the **skill side is implemented** (store, HUD, wire routes and scaffold, `observations pull`, `observations verify-connector`, `brief`, audit mode). The **app side is not started**. The wire contract below was checked against the skills repo's published contract (`system-diagnostics/references/observation-connector-contract.md` and `observation_contract.schema.json`); the three fingerprint test vectors were reproduced by the skill's code. Anything about the app's structure is marked *assumption* and must be confirmed by the app owner.

## How an agent should use this file (instructions and ready-to-paste prompt)

1. If this file already existed in the project in another version, **merge, do not overwrite**: keep the project's milestones, rules and wording; replace only the **Wire Contract v1** section with the one below (it wins on conflicts) and keep the test vectors verbatim.
2. Resolve every *assumption* (A1-A5) against the real code before editing, and write the confirmed answers into the plan.
3. Work one milestone per turn; never enable `FRONTIER_DEBUG_OBSERVATIONS` outside local development.

**Ready-to-paste prompt (Claude Code or Gemini/Antigravity):**

```text
Read .TODO/debug_observation_connector_adoption_plan.md. Adapt it to this repository: confirm assumptions A1-A5 by reading the code (framework, dashboard origin, .diagnostics conventions, AGENTS.md size rules), rewrite the placeholders (<backend_dir>, <dashboard_dir>, <router or app setup file>) with real paths, and choose Tier A or Tier B (ask me with ask_question / AskUserQuestion if unclear). Do not change the Wire Contract v1 section. Then execute Milestone 1 only: routes behind FRONTIER_DEBUG_OBSERVATIONS=1, loopback only, tests in tests/test_diagnostics_contract.py, and the manual conformance checklist. Run the verifier, report Verified / Not verified, and stop. I will say "continue" for the next milestone.
```

## What the user wants (intent)

1. While testing the app, the user picks elements and records short sessions in a DevTools-style HUD, then logs **findings** (something looks wrong) and **ideas** (something to build) as structured observations.
2. Later the user tells an agent "audit this app". The agent connects to the running app, lists everything pending, correlates observations with server errors, and continues with the project's **FOR AUDITS** workflow (alignment against `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`, P0-P2 bug catalog, why current tests and probes missed each bug, `/grill-me`, then plans).
3. This must work from Claude Code and Gemini/Antigravity agents, from a normal developer machine, with no debug data leaving the machine and nothing active unless explicitly enabled.

## Who provides what

| Skill side (antigravity-skills repo) | App side (this plan) |
| :--- | :--- |
| HUD script bundle (`/api/diagnostics/hud.js` content) | Serve the bundle, only when the debug flag is on |
| `diagnose.py observations list/show/triage/resolve/dismiss/add` | Persist observations so the routes below reflect them |
| `diagnose.py observations pull --url ...` (reads the GET routes) | Implement the GET routes |
| `diagnose.py observations verify-connector --url ...` (conformance) | Pass it |
| `diagnose.py brief [--run-probes] [--pull URL]` | Nothing; it only calls the routes |
| `/frontier-architect audit <app>` recipe | Keep `docs/architecture/*.md` current |
| Optional Python scaffold (`traces --scaffold ... --with-observations`) | Choose it (Tier A) or implement the contract by hand (Tier B) |

**Timeline:** all skill-side pieces are available now (HUD, routes, scaffold, `pull`, `verify-connector`, `brief`, audit mode). Either tier can start immediately; run `verify-connector` for conformance.

## Assumptions to verify (about this app; none confirmed)

- A1. The backend is a Python ASGI app with a router or DI layer (the audit prompt mentions "Router DI", WebSocket and JSON schemas). *Confirm the framework (FastAPI/Starlette/other).*
- A2. The UI lives in `dashboard/` and is served by the backend or a dev server on the same origin (the HUD calls the app's own `/api/diagnostics/...`). *If the dashboard uses a different origin, same-origin is lost; see Risks.*
- A3. The app already has `.diagnostics/` conventions and probes (`.diagnostics/probes/`) and uses `diagnose.py` from `system-diagnostics`. *Confirm the path the app uses to find the skill.*
- A4. Project rules: `AGENTS.md` must stay under 10 KB and `.agents/rules/` holds extra rules; new UI components need approval (so the HUD is an injected dev overlay, not a dashboard component). *Confirm with the owner.*
- A5. Much of the app's live traffic is WebSocket. **Contract v1 does not capture WebSocket frames**; only fetch/XHR, clicks, navigation, console and JS errors are recorded.

## Decision needed from the app owner

**Tier A (recommended for Python apps; available now):** generate the bridge with `python "<skill_dir>/scripts/diagnose.py" traces --scaffold fastapi --dest <backend_dir> --with-observations` (use `generic` or `flask` if the framework differs), then wire 3 lines. **Tier B (any language):** implement the routes below by hand in the app's own router, storing observations wherever suits the app (recommended layout: `.diagnostics/observations.jsonl` plus `.diagnostics/observation_catalog.json`, so local agent runs can also read them directly). Both tiers must pass `verify-connector`.

## Wire Contract v1 (canonical copy; the source of truth is `system-diagnostics/references/observation-connector-contract.md` in the skills repo; machine-readable shapes in `observation_contract.schema.json`)

Base path `/api/diagnostics`. **Availability:** routes exist only when env `FRONTIER_DEBUG_OBSERVATIONS=1`; otherwise answer `404` for all of them. **Access:** loopback clients only (`127.0.0.1`, `::1`); everything else `403`. Every response carries `X-Diagnostics-Contract: 1`. Errors are `{"error":"<code>","message":"..."}` with codes `invalid_json`, `invalid_record`, `payload_too_large`, `forbidden`, `not_found`, `unsupported_media_type`.

| Route | Request | Success | Errors |
| :--- | :--- | :--- | :--- |
| `GET /health` | none | `200 {"schema":1,"enabled":true,"contract_version":1,"store":"ok"}` | n/a |
| `POST /observation` | `Content-Type: application/json`, body = record; optional `?dry_run=1` | `201 {"id":"OBS-001","fingerprint":"OBS-ELEMENT-ab12cd","status":"open","deduplicated":false}`; `200` with `"deduplicated":true` if the fingerprint exists; `200` with `"dry_run":true` and nothing stored when `dry_run=1` | `400 invalid_json\|invalid_record`, `403`, `413` (body > 64 KB), `415` |
| `GET /observations` | `status` (default `active`), `kind`, `limit` (default 20, max 200) | `200 {"schema":1,"count":N,"truncated":false,"observations":[{"id","fingerprint","status","kind","page_path","selector","message","occurrence_count","last_seen"}]}` | `400 invalid_record` (bad `status`, `kind` or `limit`), `403` |
| `GET /observations/{id_or_fingerprint}` | none | `200` full entry (fields below) | `404 not_found`, `403` |
| `GET /hud.js` | none | `200`, `Content-Type: application/javascript`, `Cache-Control: no-store`, body = HUD bundle | `403` |

**Record (POST body):** `{"schema":1,"ts":"<ISO UTC>","kind":"element|error|network|note|idea","page_path":"/dashboard","selector":"main > button#save","rect":{"x":0,"y":0,"w":0,"h":0},"attrs":{"tag":"button","id":"save","class":"btn","data-testid":"save","role":"button","aria-label":"Save"},"message":"Save does nothing","recording_id":"rec-8f3a2c","window":{"started_at":"...","stopped_at":"..."},"timeline":[{"t":0,"type":"click|input|nav|fetch|console|error","target":"...","status":200,"ms":41}]}`. **Write limits:** record <= 64 KB; `message` <= 500 chars; `timeline` <= 50 events (drop oldest); rotate the raw file at 5 MB (keep one backup). **Redaction (server-side, mandatory):** drop any field named `value`, `password`, `authorization`, `cookie` at any depth; never store request or response bodies.

**Statuses:** `open`, `triaged`, `in_progress` (active); `resolved`, `dismissed` (closed). A recurrence of a `resolved` fingerprint reopens it.

**Fingerprint (must match exactly so apps and the skill deduplicate the same way):** normalize the message by lowercasing, removing `0x[0-9a-f]+`, removing `\d{5,}`, then splitting on whitespace and rejoining with single spaces. `target` = `selector`, or the URL path for `network`, or empty. Hash the UTF-8 string `kind|page_path|target|normalized_message` with SHA-256 and take the first 6 hex characters; id form `OBS-<KIND uppercase, max 7 chars>-<6hex>`. **Test vectors:** (`element`, `/dashboard`, `main > button#save`, `"Save   does NOTHING"`) -> `OBS-ELEMENT-fdd3fe`; (`error`, `/tracker`, `/api/frames`, `"Request 123456 failed at 0xDEADBEEF"`) -> `OBS-ERROR-f93b8a`; (`idea`, `/dashboard`, empty, `"Add a pause button"`) -> `OBS-IDEA-eca73f`.

**Full entry (`GET /observations/{id}`):** the record fields plus `id`, `fingerprint`, `status`, `first_seen`, `last_seen`, `occurrence_count`, `correlated_traces` (list of trace fingerprints), `root_cause`, `missed_by` (list), `proposed_guard`, `resolution`, `linked_plan`, `linked_commit`, `history` (list of `{ts, from, to, note}`).

**HUD to app header:** while recording, the HUD adds `X-Debug-Recording-Id: rec-<6hex>` to every fetch or XHR. If the app wants exact correlation, it copies that header's value into the context of any exception it logs as `recording_id`.

## Milestone 1: Contract routes behind the debug gate (Tier A or Tier B)

- [ ] **`<backend_dir>/diagnostics_observations.<ext>`**: implement `GET /health`, `POST /observation` (with `?dry_run=1`), `GET /observations`, `GET /observations/{id}` and `GET /hud.js` exactly as in the Wire Contract; register them **only** when `FRONTIER_DEBUG_OBSERVATIONS=1`; enforce the loopback check, 64 KB limit, `415` for non-JSON, redaction, dedup by fingerprint and the `X-Diagnostics-Contract: 1` header. Tier A: generated by the skill's scaffold instead of hand-written.
- [ ] **`<backend_dir>/<router or app setup file>`**: mount the routes (3 lines for Tier A; one include for Tier B). Nothing is mounted and nothing imported at startup when the flag is off.
- [ ] **`tests/test_diagnostics_contract.py`**: with the app's test client, cover every Wire Contract row: gating (flag off gives 404 for all routes), loopback (a non-loopback client address gives 403), invalid JSON, invalid record, oversize, wrong content type, dedup (`200 deduplicated:true`), `dry_run` stores nothing, redaction (a posted `password` key never appears in `GET`), `GET` list defaults to active items only, `GET` unknown id gives 404, `hud.js` headers, the three fingerprint test vectors.

**Verifier**: `python -m unittest discover -s tests -p "test_diagnostics_contract.py"` and the manual checklist at the end of this file.
**Exit criteria:** every row passes; no new route exists when the flag is off; no observation data in git (`.diagnostics/` ignored).

## Milestone 2: HUD in the dashboard, dev only *(Deferred to Next Turn / Milestone)*

The HUD bundle is served by the skill's generated bridge (Tier A) or must be copied from `system-diagnostics/assets/hud_*.js` (Tier B). `window.__FRONTIER_OBS_ENDPOINT__` overrides the POST endpoint for a different origin.

- [ ] **`<dashboard_dir>/<dev index or layout template>`**: when the flag is on, include `<script>window.__FRONTIER_DEBUG__ = true;</script><script src="/api/diagnostics/hud.js"></script>`; never in production builds.
- [ ] **`tests/test_dashboard_debug_hud.py`**: the template contains the two script tags only when the flag is on; none when off.
- [ ] **manual E2E (record the result in the PR)**: open the dashboard, Pick Element, Record, trigger a fetch, Stop, Log Observation; `GET /api/diagnostics/observations` shows it; the request had `X-Debug-Recording-Id`.

**Verifier**: `python -m unittest discover -s tests -p "test_dashboard_debug_hud.py"` plus the manual E2E.
**Exit criteria:** HUD invisible and inert without the flag; no new dashboard component created (the HUD is an injected overlay); same-origin posts work.

## Milestone 3: Trace stamping for exact correlation *(Deferred to Next Turn / Milestone)*

- [ ] **`<backend_dir>/<error logging or trace middleware>`**: copy the `X-Debug-Recording-Id` request header into the exception context as `recording_id` (Tier A: use the skill's trace middleware). Document that WebSocket-handler exceptions are not stamped in v1.
- [ ] **`tests/test_trace_recording_id.py`**: a request carrying the header that raises produces a trace event whose context holds the same `recording_id`; a request without the header has none.

**Verifier**: `python -m unittest discover -s tests -p "test_trace_recording_id.py"`
**Exit criteria:** correlated traces appear in `observations show` once the skill side lands.

## Milestone 4: Developer workflow and audit hand-off *(Deferred to Next Turn / Milestone)*

- [ ] **`docs/architecture/CURRENT_ARCHITECTURE.md`**: add a short "Debug observation connector" section (routes, flag, tier chosen, limits including WebSocket).
- [ ] **`.agents/rules/debug-observations.md`** (and one pointer line in `AGENTS.md`, keeping it under 10 KB): how to enable the flag, how to run `observations list`, `pull` and `brief`, and the privacy rule that observations never leave the machine.
- [ ] **FOR AUDITS prompt (project workflow)**: apply the edits in the next section.
- [ ] **PR notes**: record which tier was chosen, the Milestone 1 and 2 results, and the output of `verify-connector`.

**Verifier**: `python -m unittest discover -s tests -p "test_*.py"` and `python "<skill_dir>/scripts/diagnose.py" observations verify-connector --url http://127.0.0.1:<port>` (all `PASS`; the loopback rule shows `SKIP`).
**Exit criteria:** an agent that has never seen this repo can enable the flag, list pending observations and run the audit using only the docs.

## Suggested edits to the FOR AUDITS prompt (the skill side has shipped; apply when the app's connector passes `verify-connector`)

- In section 1's command batch, add: `diagnose.py brief --run-probes --pull http://127.0.0.1:<port>` (it replaces running `traces`, `probe list` and `probe run` separately and also shows active observations; a section it cannot read shows `UNAVAILABLE (reason)` and counts as UNVERIFIED). Without `--pull`, run `observations pull --url http://127.0.0.1:<port>` first for an app in a container. Keep `surface --verify`, `scan`, `audit` and `arch-map` if finer output is wanted.
- Replace the `[Finding N]` placeholders in section 2 with: "Findings come from active observations of kinds `element`, `error`, `network`, `note` (`observations list --json`); add any extra findings below."
- Replace the `[Idea N]` placeholders in section 3 with: "Ideas come from active observations of kind `idea` (`observations list --kind idea --json`); add any extra ideas below."
- In section 4, record each answer with `observations triage --id <ID> --root-cause "..." --missed-by tests,surface,... --guard "<proposed upgrade>"` so the "why did our tools miss it" analysis stays queryable.
- After a verified fix, close the loop with `observations resolve --id <ID> --resolution "..." --commit <sha>`.
- Under Claude Code the prompt's `ask_question` is `AskUserQuestion` and `Model: 'flash'` research subagents are `Explore` agents; the skill's adapter documents the mapping. `/frontier-architect audit <app>` runs this whole sequence (`frontier-architect/references/audit-recipe.md`).

## Manual conformance checklist (works with any language; use before `verify-connector` exists)

Start the app with `FRONTIER_DEBUG_OBSERVATIONS=1`, then (replace the port):
1. `curl -si http://127.0.0.1:8000/api/diagnostics/health` -> `200`, header `X-Diagnostics-Contract: 1`, body has `"contract_version":1`.
2. `curl -si -X POST 'http://127.0.0.1:8000/api/diagnostics/observation?dry_run=1' -H 'Content-Type: application/json' -d '{"schema":1,"ts":"2026-11-26T12:00:00Z","kind":"note","page_path":"/x","message":"check"}'` -> `200` with `"dry_run":true`.
3. Same URL with body `not json` -> `400`; with `-H 'Content-Type: text/plain'` -> `415`; with a body over 64 KB -> `413`.
4. Real `POST` (no `dry_run`) of the valid body -> `201`; repeat it -> `200` with `"deduplicated":true`.
5. `curl -s 'http://127.0.0.1:8000/api/diagnostics/observations'` -> the item appears; `?kind=idea` hides it.
6. `curl -si http://127.0.0.1:8000/api/diagnostics/observations/OBS-DOES-NOT-EXIST` -> `404`.
7. `curl -si http://127.0.0.1:8000/api/diagnostics/hud.js` -> `Content-Type: application/javascript`, `Cache-Control: no-store`.
8. Restart **without** the env var -> every route above answers `404`.
9. From another machine or interface (not loopback), any route -> `403` (manual only).

## Security checklist for the app owner

Flag off by default and absent from production configs; loopback-only enforcement tested; `.diagnostics/` gitignored; redaction tested with a `password` key; HUD script never included in production builds; no bodies, cookies or credentials stored; `pull` is loopback-only by default on the skill side.

## Risks and known limits

| Risk or limit | Mitigation |
| :--- | :--- |
| Dashboard on a different origin from the API (A2) | Run both behind one dev proxy, or set `window.__FRONTIER_OBS_ENDPOINT__` and add a narrowly scoped CORS rule for loopback only |
| Strict CSP blocks the HUD script | Serve `hud.js` from the same origin (done by design); add a nonce in dev if needed |
| WebSocket traffic is not recorded (A5) | Out of scope for contract v1; fetch/XHR, clicks, navigation and errors still are |
| Choosing between tiers | Start with Tier B and `verify-connector`; swap to Tier A later if desired (contract identical) |
| Contract changes | `X-Diagnostics-Contract` and `GET /health` carry the version; `pull` and `verify-connector` refuse a mismatch |

## Definition of Done (app side)

- [ ] Milestone 1 tests pass and the manual checklist passes (all nine items).
- [ ] With the flag on, the HUD works in the dashboard; with it off, nothing is mounted, served or injected.
- [ ] `observations pull` against the running app imports its observations.
- [ ] `verify-connector` reports all `PASS` .
- [ ] The FOR AUDITS prompt edits are applied after the skill side ships, and a full audit run starts from `brief` and observations.
- [ ] `CURRENT_ARCHITECTURE.md`, `.agents/rules/` and `AGENTS.md` (< 10 KB) updated; PR notes list the tier chosen and the test evidence.
