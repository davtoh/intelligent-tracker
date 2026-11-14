.. _memory_and_world_query:

Semantic Memory, Confidence Engine & WorldQueryEngine
=====================================================

The **Semantic Memory & World Query** subsystem (``intelligent_tracker.memory``) provides
long-term multi-modal entity confidence calibration, SQLite FTS5 timeline indexing,
and offline-first natural-language Q&A across camera streams, spatial zones, and
security events.

Architecture Overview
---------------------

.. code-block:: text

    +--------------------+     Sightings / Zones / RSAC     +--------------------+
    |      EventBus      | ===============================> |   EventFTSIndex    |
    +--------------------+                                  +--------------------+
              |                                                       |
              v                                                       v
    +--------------------+     Calibrated State (0..1)      +--------------------+
    |  ConfidenceEngine  | <==============================> | TrackerDB (SQLite) |
    +--------------------+                                  | FTS5 + Confidence  |
              |                                             +--------------------+
              |                       +--------------------+          |
              +---------------------> |  WorldQueryEngine  | <--------+
                                      +--------------------+
                                        |                |
                +-----------------------+                +----------------------+
                v                                                               v
    +-----------------------+                                     +--------------------------+
    |  LocalDeterministic   |                                     |  PrivacyMaskingFilter    |
    |  Provider (Offline)   |                                     |  -> GeminiSemanticProvider|
    +-----------------------+                                     +--------------------------+

Key Capabilities
----------------

1. **Long-Term Confidence Engine** (``ConfidenceEngine``):
   Combines facial and body Re-ID scores, temporal streak consistency,
   ``CrossCameraTopology`` transition priors, and human Active Learning feedback
   (confirmations, reassignments, dismissals) while applying ambiguity penalties
   and configurable half-life staleness decay.
2. **FTS5 Semantic Timeline Indexing** (``EventFTSIndex``):
   Subscribes to ``EventBus`` events (sightings, zone dwell/entry/exit, tripwire crossings,
   RSAC violations, pet activity, entity state transitions) and indexes normalized
   documents into ``world_timeline_events`` and ``world_timeline_fts`` for BM25 ranking.
3. **Offline-First Q&A & Pluggable Providers** (``WorldQueryEngine``):
   Parses natural-language queries deterministically (entities, cameras, zones, event types,
   relative time windows, and intent) and formats grounded answers via
   ``LocalDeterministicProvider`` with zero external API dependencies. Optional cloud
   synthesis via ``GeminiSemanticProvider`` runs behind ``PrivacyMaskingFilter``
   (metadata-only egress by default) and automatically falls back locally on failure.

REST API Reference
------------------

``POST /api/world/query``
   Executes a semantic world query against FTS5 timelines, ``ConfidenceEngine``, and
   ``WorldGraph``. Accepts JSON fields ``query`` (required), optional overrides
   (``entity_id``, ``camera_id``, ``zone_id``, ``event_type``, ``start_time``, ``end_time``),
   ``limit`` (1--200), and ``include_world_snapshot``.

``GET /api/world/confidence/{entity_id}``
   Returns calibrated long-term confidence telemetry for ``entity_id``, supporting
   an optional ``?timestamp=<unix_seconds>`` parameter for point-in-time decay evaluation.

``GET /api/world/timeline``
   Searches FTS5 timeline events with ``?q=`` (or ``?query=``) plus structured filters
   (``entity_id``, ``camera_id``, ``zone_id``, ``event_type``, ``start_time``,
   ``end_time``, ``limit``, ``require_all``).

``GET /api/world/snapshot``
   Returns a JSON-serializable topology and entity snapshot of the active ``WorldGraph``.

``GET /api/world/entities``
   Lists live ``WorldEntity`` nodes from the active ``WorldGraph`` with optional
   ``?camera_id=`` and ``?min_confidence=`` filters.

CLI Parity (``ask``)
--------------------

Both ``intelligent-tracker ask`` and ``intelligent-tracker-ctl ask`` expose the same
query capabilities from the terminal in offline (local SQLite ``TrackerDB``) or remote
(dashboard ``POST /api/world/query``) mode.

Scenario Combinations Matrix
----------------------------

.. list-table::
   :widths: 24 22 22 32
   :header-rows: 1

   * - Scenario / Objective
     - Mode / Inputs
     - Key Parameters
     - Exact Runnable Command
   * - Offline Local Query
     - Local SQLite DB
     - ``--db``, ``--offline``
     - ``intelligent-tracker ask "Where was Alice?" --db data/tracker.db``
   * - JSON Automation Output
     - Local SQLite DB
     - ``--json``, ``--limit``
     - ``intelligent-tracker ask "Show RSAC violations" --db data/tracker.db --json --limit 10``
   * - Remote Dashboard Query
     - Running Dashboard API
     - ``--url`` or ``$APP_URL``
     - ``intelligent-tracker-ctl ask "What is Alice confidence?" --url "$APP_URL"``
   * - Targeted Filter Query
     - Camera / Zone / Event
     - ``--camera``, ``--zone``, ``--event-type``
     - ``intelligent-tracker-ctl ask "vault activity" --db data/tracker.db --camera cam_02 --zone vault``

Python API Reference
--------------------

intelligent\_tracker.memory package
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: intelligent_tracker.memory
    :members:
    :undoc-members:
    :show-inheritance:

intelligent\_tracker.memory.confidence module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: intelligent_tracker.memory.confidence
    :members:
    :undoc-members:
    :show-inheritance:

intelligent\_tracker.memory.fts\_index module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: intelligent_tracker.memory.fts_index
    :members:
    :undoc-members:
    :show-inheritance:

intelligent\_tracker.memory.providers module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: intelligent_tracker.memory.providers
    :members:
    :undoc-members:
    :show-inheritance:

intelligent\_tracker.memory.query\_engine module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: intelligent_tracker.memory.query_engine
    :members:
    :undoc-members:
    :show-inheritance:

