# Step 5 Implementation Plan: Long-Term Confidence Engine & Pluggable Semantic Q&A (WorldQueryEngine)

> **Parent Master Plan**: `.TODO/world_architecture_master_roadmap.md` (Step 5)  
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (ADR-03, ADR-04, Sections 3, 4, 5, 6.2 & 6.3)  
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Next Turn / Milestone*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map`)

Static snapshot run via `diagnose.py arch-map --path .` prior to Step 5 design:
- **Codebase Scale**: 269 files scanned, 49,414 lines, 95 FastAPI routes.
- **Step 5 Pre-Flight Modularity Alerts**:
  - `intelligent_tracker/active_learning.py`: **457 lines** (`WARN 350-499L`), `ActiveLearningManager` (**13 methods**, 429 lines — exceeds 12-method ceiling). **Mandatory Split-Before-You-Grow target in Milestone 1.**
  - `intelligent_tracker/repositories/schema_manager.py`: **323 lines** (`SchemaMixin`, 9 methods). Near 350L soft ceiling — Step 5 DDL migrations MUST be extracted into a helper module (`memory_schema.py`) so `schema_manager.py` remains $\le 350$ lines.
  - `intelligent_tracker/matching/gallery.py`: **421 lines** (`WARN 350-499L`). Do NOT bloat `gallery.py` with Long-Term Confidence Engine logic; wire confidence scoring in `intelligent_tracker/world/entity_bridge.py`, `intelligent_tracker/active_learning_actions.py`, and `intelligent_tracker/pipeline/bundle.py`.
- **SQLite Baseline**:
  - `PRAGMA user_version` is currently `0` (`SchemaMixin._apply_schema_migrations()` uses idempotent `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` guards).
  - Python runtime `sqlite3` empirically supports **FTS5** (`CREATE VIRTUAL TABLE ... USING fts5(...)`).
  - `SQLiteConnectionCoordinator` (`intelligent_tracker/repositories/connection.py`) provides WAL mode (`PRAGMA journal_mode = WAL`), `busy_timeout = 10000`, and path-keyed `RLock` coordination.

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts
1. **`ActiveLearningManager` (`intelligent_tracker/active_learning.py`)**:
   - Preserve exact constructor signature and all 13 public/legacy methods (`consider_candidate`, `maybe_queue_candidate`, `list_pending`, `_extract_crop_embedding`, `confirm`, `reassign`, `enroll_new`, `dismiss`, `confirm_candidate`, `reassign_candidate`, `enroll_as_new`, `dismiss_candidate`) for `dashboard/routers/rsac.py`, `dashboard/dependencies.py`, `intelligent_tracker/pipeline/bundle.py`, `intelligent_tracker/matching/gallery.py`, and existing unit tests.
2. **`TrackerDB` (`intelligent_tracker/database.py`)**:
   - Preserve all 17 existing tables and existing `PRAGMA` settings; evolve schema via idempotent `PRAGMA user_version = 1` migration without losing existing `entities`, `entity_signatures`, or `sightings` rows.
3. **Offline-First & Privacy Boundaries (`docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` §6.3)**:
   - All detection, Re-ID, Active Learning, confidence scoring, FTS5 indexing, and structured Q&A MUST work 100% offline with zero API keys.
   - External `SemanticProvider` adapters must pass through a `PrivacyMaskingFilter` (metadata-only by default; zero raw crops or PII sent externally unless explicitly enabled).
4. **Python Modernization (`AGENTS.md` §1)**:
   - Zero `from __future__ import ...` imports anywhere; use Python 3.10–3.12+ native union syntax (`X | Y`) and built-in generics (`list[...]`, `dict[...]`).
5. **No Hardcoded Infrastructure**:
   - Zero literal `localhost`, `127.0.0.1`, ports, or API keys in source or plans; resolve endpoints and provider keys strictly via environment variables or caller arguments.

### Modularity Budgets
- Every new or refactored `.py` file MUST stay **$\le 350$ lines** (hard ceiling 500L), classes **$\le 10$–$12$ methods**, functions **$\le 40$ lines**, and FastAPI route handlers **$\le 15$–$25$ lines**.

---

## 3. Target Architecture Overview

| Component | Target Files | Budget Target | Responsibility |
| :--- | :--- | :--- | :--- |
| **Active Learning Split** | `intelligent_tracker/active_learning_triage.py`, `intelligent_tracker/active_learning_actions.py`, `intelligent_tracker/active_learning.py` | $< 180$L each, $\le 10$ methods | Triage gating/cropping, operator resolution + confidence feedback, thin backward-compatible facade |
| **Memory Schema & Repo** | `intelligent_tracker/repositories/memory_schema.py`, `intelligent_tracker/repositories/memory_repo.py`, `intelligent_tracker/database.py` | $< 260$L each, $\le 10$ methods | `PRAGMA user_version = 1` migration, `entity_confidence_state`, `world_timeline_fts` (FTS5), `MemoryMixin` |
| **Confidence Engine** | `intelligent_tracker/memory/confidence.py` | $< 260$L, $\le 10$ methods | Multi-modal evidence accumulation (face, body, temporal streak, topology prior, human confirmation) & ambiguity/staleness decay |
| **Semantic Timeline FTS** | `intelligent_tracker/memory/fts_index.py` | $< 220$L, $\le 10$ methods | `EventBus` subscriber indexing sightings, zone crossings, RSAC breaches, pet events, and clip captions into FTS5 |
| **Pluggable Providers** | `intelligent_tracker/memory/providers.py` | $< 220$L, $\le 10$ methods | `SemanticProvider` protocol, `PrivacyMaskingFilter`, `LocalDeterministicProvider`, `GeminiSemanticProvider`, `MockSemanticProvider` |
| **World Query Engine** | `intelligent_tracker/memory/query_engine.py` | $< 260$L, $\le 10$ methods | Deterministic intent/FTS/confidence/graph resolver + optional provider synthesis returning structured `WorldQueryResult` |
| **Dashboard & CLI Parity** | `dashboard/routers/world.py`, `dashboard/dependencies.py`, `dashboard/app.py`, `intelligent_tracker/cli/ask.py`, `intelligent_tracker/cli/ctl.py` | $< 180$L each, routes 5–15L | `POST /api/world/query`, `GET /api/world/confidence/{entity_id}`, `GET /api/world/timeline`, and `intelligent-tracker ask "..."` |

---

## 4. Phased Implementation Milestones

### Milestone 1: Pre-Flight `active_learning.py` Split & SQLite FTS5 / Confidence Schema (`PRAGMA user_version = 1`) — *Active Execution Target*
- [x] **intelligent_tracker/active_learning_triage.py**: Extract candidate confidence range gating, per-track debouncing cache, BGR crop persistence, and `ReviewItemQueuedEvent` dispatch into a cohesive collaborator (`< 180` lines, $\le 8$ methods).
- [x] **intelligent_tracker/active_learning_actions.py**: Extract operator review resolution (`confirm`, `reassign`, `enroll_new`, `dismiss`, and `*_candidate` dict APIs) with optional `on_feedback` callback hook for confidence reinforcement (`< 180` lines, $\le 10$ methods).
- [x] **intelligent_tracker/active_learning.py**: Refactor `ActiveLearningManager` into a thin facade (`< 180` lines, $\le 10$ methods) delegating to triage and actions modules while preserving 100% of its public API.
- [x] **intelligent_tracker/repositories/memory_schema.py**: Implement idempotent `PRAGMA user_version = 1` schema migration adding `entity_confidence_state` table, `world_timeline_events` metadata table, and `world_timeline_fts` SQLite FTS5 virtual table (`< 140` lines).
- [x] **intelligent_tracker/repositories/schema_manager.py**: Invoke `apply_memory_schema_migrations()` inside `_apply_schema_migrations()` while keeping `schema_manager.py` under 350 lines.
- [x] **intelligent_tracker/repositories/memory_repo.py**: Create `MemoryMixin` (`< 240` lines, $\le 10$ methods) for thread-safe upserts/reads of `entity_confidence_state`, timeline FTS5 document indexing, and BM25-ranked timeline search, and compose it into `TrackerDB` in `intelligent_tracker/database.py`.
- [x] **tests/test_active_learning.py & tests/test_memory_repository.py**: Verify full parity of the split `ActiveLearningManager` (all branches), idempotent `PRAGMA user_version = 1` upgrade preserving pre-existing data, FTS5 indexing/BM25 query accuracy, and concurrent WAL write safety in `TemporaryDirectory()` isolation.

**Definition of Done (DoD)**:
- [x] `intelligent_tracker/active_learning.py` is $< 200$ lines and `ActiveLearningManager` has $\le 10$ methods.
- [x] `PRAGMA user_version` upgrades cleanly from `0` to `1` on both fresh and pre-existing databases with zero data loss.
- [x] Targeted tests (`tests/test_active_learning.py`, `tests/test_memory_repository.py`, `tests/test_modernization.py`) pass 100% in headless mode (`MPLBACKEND=Agg`).

---

### Milestone 2: Long-Term Confidence Engine & Pipeline / Active-Learning Integration — *Deferred to Next Turn / Milestone*
- [x] **intelligent_tracker/memory/__init__.py & intelligent_tracker/memory/confidence.py**: Implement `ConfidenceEvidence` dataclass and `ConfidenceEngine` (`< 260` lines, $\le 10$ methods) computing calibrated presence confidence in `[0.0, 1.0]` from multi-modal signals (face similarity, body similarity, temporal streak consistency, `CrossCameraTopology` transition prior, human confirmations) balanced against ambiguity conflict and staleness time-decay.
- [x] **intelligent_tracker/world/entity_bridge.py & intelligent_tracker/world/nodes.py**: Feed `ConfidenceEngine.record_observation()` on tracked entity updates so `WorldEntity.confidence` reflects calibrated multi-modal confidence without blocking 30 FPS tracking or bloating `matching/gallery.py`.
- [x] **intelligent_tracker/active_learning_actions.py**: Hook `confirm` / `reassign` / `dismiss` operator decisions into `ConfidenceEngine.record_human_feedback()` so verified matches reinforce identity confidence and reassignments/dismissals decay conflicting priors.
- [x] **intelligent_tracker/pipeline/bundle.py & intelligent_tracker/pipeline/engine.py**: Instantiate `ConfidenceEngine` backed by `TrackerDB` (`MemoryMixin`) in `PipelineBundle` and wire it cleanly into `WorldEntityBridge` and `ActiveLearningManager`.
- [x] **tests/test_confidence_engine.py**: Add unit and integration tests proving repeated consistent multi-modal sightings measurably increase presence confidence, ambiguous/conflicting or stale observations decay confidence, human confirmation boosts confidence, and state persists across `TrackerDB` restarts.

**Definition of Done (DoD)**:
- [x] `ConfidenceEngine` unit and persistence tests pass 100% across all branches (cold start, multi-modal boost, topology prior boost, ambiguity penalty, time decay, human confirm/reject).
- [x] `diagnose.py arch-map --path .` confirms all modified files remain below 350 lines.

---

### Milestone 3: Semantic Timeline FTS Index & Pluggable `WorldQueryEngine` — *Deferred to Next Turn / Milestone*
- [x] **intelligent_tracker/memory/fts_index.py**: Implement `EventFTSIndex` (`< 220` lines, $\le 10$ methods) subscribing to `EventBus` (`Sighting`, `ZoneEvent`, `TripwireCrossEvent`, `RSACViolationEvent`, `PetActivityEvent`, `EntityStateChangedEvent`) and indexing normalized timeline documents + optional clip captions into `TrackerDB` FTS5 outside locks.
- [x] **intelligent_tracker/memory/providers.py**: Implement `@runtime_checkable SemanticProvider` protocol, `PrivacyMaskingFilter` (metadata-only default + PII/crop redaction guard), `LocalDeterministicProvider` (zero-dependency offline formatter), `GeminiSemanticProvider` (optional cloud adapter configured solely via environment variables with safe offline fallback), and `MockSemanticProvider` (`< 220` lines).
- [x] **intelligent_tracker/memory/query_engine.py**: Implement `WorldQueryEngine` (`< 260` lines, $\le 10$ methods) combining deterministic query parsing (entity name, zone, camera, event type, time range, confidence intent) + FTS5 BM25 retrieval + `ConfidenceEngine` lookup + `WorldGraph.snapshot()`, with optional `SemanticProvider` natural-language synthesis.
- [x] **intelligent_tracker/pipeline/bundle.py**: Attach `EventFTSIndex` to `EventBus` when memory indexing is enabled so live pipeline events flow into the searchable timeline.
- [x] **tests/test_world_query_engine.py**: Verify `EventBus` $\rightarrow$ `EventFTSIndex` ingestion (sightings, zone crossings, RSAC breaches, clip captions), offline structured/FTS Q&A accuracy, `MockSemanticProvider` swapping, `GeminiSemanticProvider` unconfigured/offline error handling, and `PrivacyMaskingFilter` egress redaction.

**Definition of Done (DoD)**:
- [x] Offline natural-language/structured queries accurately retrieve sightings, presence confidence, and security timelines without any external API key.
- [x] Optional VLM/LLM provider protocol and privacy filter pass all isolation and fallback branch tests.

---

### Milestone 4: Dashboard API, CLI `ask` Parity, Sphinx Documentation & Final Verification — *Deferred to Next Turn / Milestone*
- [x] **dashboard/routers/world.py**: Create `APIRouter(prefix="/api/world", tags=["World Intelligence & Query"])` (`< 180` lines, handlers 5–15L) exposing `POST /api/world/query`, `GET /api/world/confidence/{entity_id}`, and `GET /api/world/timeline`.
- [x] **dashboard/dependencies.py & dashboard/app.py**: Register `get_world_query_engine` via `app.state` / `Depends` (preserving existing DI patterns) and mount `world_router` in `dashboard/app.py`.
- [x] **intelligent_tracker/cli/ask.py, intelligent_tracker/cli/runner.py & intelligent_tracker/cli/ctl.py**: Implement `intelligent-tracker ask "..."` and `intelligent-tracker-ctl ask "..."` supporting offline `TrackerDB`/`WorldQueryEngine` queries and optional remote server mode via env/flag (`--url`), with JSON and human-readable output.
- [x] **documentation/**: Add/update Sphinx documentation in `documentation/` covering `intelligent_tracker.memory`, `ConfidenceEngine`, `WorldQueryEngine`, `POST /api/world/query`, and `intelligent-tracker ask`.
- [x] **tests/test_world_query_api.py & tests/test_cli_ask.py**: Test `POST /api/world/query`, confidence/timeline endpoints via FastAPI `TestClient` with isolated `TemporaryDirectory()` DBs, and CLI `ask` subcommand parity (offline + remote mock + error branches).
- [x] **CHANGELOG.md**: Record milestone completion via `diagnose.py changelog add`.

**Definition of Done (DoD)**:
- [x] Full regression test suite (`python -m unittest discover tests`) passes 100% in headless mode (`MPLBACKEND=Agg`).
- [x] Sphinx build (`python -m sphinx -W --keep-going documentation/ documentation/_build/html/`) passes with zero warnings.
- [x] `diagnose.py arch-map --path .` reports zero new modularity ceiling violations and clean `intelligent_tracker/` $\leftrightarrow$ `dashboard/` layering.

---

## 5. Scenario Combinations Matrix

| Scenario | Configuration / Inputs | Expected Behavior | Verification Command |
| :--- | :--- | :--- | :--- |
| **Active Learning Split Parity** | `ActiveLearningManager` with isolated temp DB, mock matcher, similarity in `[0.45, 0.70)` | Debounces duplicate frames, saves crop, emits `ReviewItemQueuedEvent`, supports confirm/reassign/enroll/dismiss | `python -m unittest tests/test_active_learning.py` |
| **Schema Migration (`v0` $\rightarrow$ `v1`)** | Pre-populated `v0` SQLite DB opened by `TrackerDB` | `PRAGMA user_version` becomes `1`; existing rows preserved; `entity_confidence_state` and `world_timeline_fts` created idempotently | `python -m unittest tests/test_memory_repository.py` |
| **Confidence Reinforcement & Decay** | Repeated consistent face+body+topology sightings vs. conflicting/stale observations + human confirmation | Calibrated confidence rises monotonically on consistent sightings, drops on ambiguity/staleness, boosts on confirm | `python -m unittest tests/test_confidence_engine.py` |
| **Offline Semantic Timeline Q&A** | `WorldQueryEngine` with `LocalDeterministicProvider` + indexed sightings, zone crossings, RSAC breaches, clip captions | Returns accurate matching events, entity confidence summary, and citations with zero network calls | `python -m unittest tests/test_world_query_engine.py` |
| **Pluggable VLM/LLM & Privacy Guard** | `WorldQueryEngine` with `MockSemanticProvider` and `PrivacyMaskingFilter(metadata_only=True)` | Strips raw crops/PII before provider invocation; falls back cleanly to local deterministic answer if provider fails | `python -m unittest tests/test_world_query_engine.py` |
| **Dashboard & CLI Parity** | `POST /api/world/query` via `TestClient` and `intelligent-tracker ask "..."` against shared isolated DB | Both return consistent answers, cited timeline events, and confidence telemetry | `python -m unittest tests/test_world_query_api.py tests/test_cli_ask.py` |
| **Full Suite & Docs Gate** | Entire repository test suite + Sphinx HTML build + static `arch-map` | 100% green tests, 0 Sphinx warnings, zero modularity regressions | `python -m unittest discover tests` |

