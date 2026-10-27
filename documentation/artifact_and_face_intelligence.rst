Artifact & Face Intelligence, Active Learning & Adaptive Memory
================================================================

Overview
--------

Milestone 9 introduces modern Frontier Security capabilities into **Intelligent Tracker**:

1. **Universal Artifact & Face Enrollment**:
   Freeze-frame video cropping, interactive bounding box selection, category badges (e.g. ``person``, ``family_car``, ``delivery_truck``, ``cleaning_crew``, ``guard_dog``, ``pet``, ``vip``, ``restricted``), security role assignments, and dual-model feature extraction.
2. **Role-Based Spatial Access Control (RSAC)**:
   Fine-grained spatial access policies evaluating which categories or identities are authorized in specific zones, with time-of-day / day-of-week active schedule windows, per-entity grants/denials, and domestic pet perimeter intrusion alarm suppression.
3. **Human-in-the-Loop Active Learning ("Review & Learn" Inbox)**:
   Low-confidence candidate triage ($0.45 \le \text{similarity} < 0.70$) that queues ambiguous tracks with thumbnail crops for operator triage: **Confirm (Ground Truth)**, **Reassign**, **Enroll New**, or **Dismiss**.
4. **Locked Anchor Descriptors & Continuous Adaptive Memory**:
   Immutable ground-truth locked anchor signatures, bounded Exponential Moving Average (EMA) continuous feature updating, occlusion reasoning (freezing Re-ID identity updates when tracks overlap with $\text{IoU} > 0.3$), and versioned descriptor snapshots with 1-click rollback.

Architecture Diagram
--------------------

.. code-block:: text

    +-----------------------------------------------------------------------------------+
    |                       Universal Artifact & Face Enrollment                        |
    |  - Freeze-frame crop / canvas selection / manual file upload                       |
    |  - DualModelFeatureExtractor: Primary Body/Artifact Embedding + YuNet Face Extractor |
    |  - Ground-truth Locked Anchor flagged & Version 1 snapshot persisted in SQLite    |
    +-----------------------------------------------------------------------------------+
                                              |
                                              v
    +-----------------------------------------------------------------------------------+
    |               Real-Time Tracking & Occlusion-Aware Re-ID Engine                   |
    |  - Spatial IoU pairwise checks: flag tracks as is_cluttered when IoU > 0.3        |
    |  - Freeze Re-ID feature accumulation during occlusions to prevent identity swap   |
    |  - Bounded EMA adaptation: update centroid only if sim(anchor) >= 0.65            |
    +-----------------------------------------------------------------------------------+
                      |                                               |
         similarity in [0.45, 0.70)                       similarity >= 0.70
                      v                                               v
    +---------------------------------------+       +-----------------------------------+
    |    Active Learning Review Queue       |       |  Role-Based Spatial Access (RSAC) |
    | - Debounced candidate triage          |       | - Allowed/denied category filter  |
    | - Operator Action: Confirm Ground-    |       | - Time & day schedule windows     |
    |   Truth, Reassign, Enroll New, Dismiss|       | - Entity allow/deny overrides     |
    +---------------------------------------+       | - Pet perimeter alarm suppression |
                                                    +-----------------------------------+

Universal Enrollment & Dual-Model Feature Extraction
----------------------------------------------------

The ``UniversalEnrollmentManager`` provides enrollment for any real-world entity: humans, vehicles, delivery vans, guard dogs, domestic pets, tools, or packages.

.. code-block:: python

    from intelligent_tracker.enrollment import UniversalEnrollmentManager
    from intelligent_tracker.database import TrackerDB

    db = TrackerDB("data/tracker.db")
    enrollment_mgr = UniversalEnrollmentManager(db=db)

    # Enroll from a freeze-frame crop
    result = enrollment_mgr.enroll(
        name="Chief Medical Officer",
        category="vip",
        crop=crop_image,
        notes="Hospital executive with master access",
        security_role="executive",
        is_anchor=True,
    )

Feature extraction is performed by ``DualModelFeatureExtractor``, which couples artifact/body Re-ID (e.g. OSNet or Color Histogram) with localized facial biometric extraction via ``YuNetFaceDetector``:

.. math::

    \mathbf{f}_{\text{fused}} = \left[ \mathbf{f}_{\text{primary}} \,\|\, \mathbf{f}_{\text{face}} \right], \quad \hat{\mathbf{f}} = \frac{\mathbf{f}_{\text{fused}}}{\|\mathbf{f}_{\text{fused}}\|_2}

Role-Based Spatial Access Control (RSAC)
----------------------------------------

``RSACManager`` evaluates spatial zone authorizations at runtime:

- **Semantic Category Whitelists & Denials**: Specify allowed and denied categories (e.g., allow ``cleaning_crew`` in ``vault``, deny ``person``).
- **Time-of-Day & Day-of-Week Schedules**: Define active operating windows (e.g. Monday-Friday 08:00 to 18:00).
- **Entity Overrides**: Explicitly grant or revoke access for specific entity IDs.
- **Pet Alarm Suppression**: Perimeter tripwires and intrusion zones automatically suppress alarms for whitelisted domestic pet categories or labels (e.g., ``pet``, ``dog``, ``cat``), routing informational ``PetActivityEvent`` alerts instead of critical breach alarms.

.. code-block:: python

    from intelligent_tracker.rsac import RSACManager

    rsac = RSACManager(db=db)
    rsac.set_rule(
        camera_id="cam_01",
        zone_id="server_room",
        allowed_categories=["staff", "vip"],
        denied_categories=["restricted"],
        schedules=[{"days": ["mon", "tue", "wed", "thu", "fri"], "start_time": "08:00", "end_time": "18:00"}],
        entity_overrides={"42": "allow"},
        alarm_on_breach=True,
    )

    decision = rsac.evaluate_access(
        camera_id="cam_01",
        zone_id="server_room",
        entity_category="staff",
        entity_id=10,
    )
    if not decision.allowed:
        print(f"RSAC Breach: {decision.reason} (Severity: {decision.severity})")

Active Learning ("Review & Learn" Inbox)
----------------------------------------

Ambiguous detections with Re-ID confidence scores in the triage window $[0.45, 0.70)$ are intercepted and debounced by ``ActiveLearningManager``.

Candidates are stored in the ``review_queue`` table and dispatched over WebSockets to the web dashboard:

.. list-table:: Operator Triage Actions
   :widths: 20 80
   :header-rows: 1

   * - Action
     - Effect on System
   * - **Confirm (Ground Truth)**
     - Confirms suggested entity identity and promotes candidate crop as an immutable **Locked Anchor** (v2, v3, etc.).
   * - **Reassign**
     - Transfers candidate crop to a different chosen entity as a Locked Anchor.
   * - **Enroll New**
     - Registers candidate crop as a newly created entity identity with initial locked descriptor version 1.
   * - **Dismiss**
     - Marks candidate as rejected (e.g., shadow, artifact blur) without mutating the Re-ID gallery.

Occlusion Reasoning & Versioned Memory Rollback
-----------------------------------------------

- **Occlusion Handling**: When two tracks intersect with $\text{IoU} > 0.3$, ``check_track_occlusions`` flags them with ``is_cluttered = True``. During clutter, Re-ID feature updates are frozen to avoid identity contamination.
- **Bounded EMA Adaptation**: Valid high-confidence matches continuously update the running centroid using:

  .. math::

      \mathbf{c}_{t+1} = (1 - \alpha) \mathbf{c}_t + \alpha \mathbf{x}_{t+1}

  The update is accepted only if the candidate observation and resulting vector satisfy:

  .. math::

      \cos(\mathbf{c}_{t+1}, \mathbf{a}_{\text{locked}}) \ge \tau_{\text{drift}} \quad (\tau_{\text{drift}} = 0.65)

- **Descriptor Rollback**: All updates record immutable snapshot rows in ``descriptor_versions``. If an identity ever drifts due to lighting or occlusion, an operator can roll back to any prior verified version in one click via ``POST /api/entities/{id}/rollback/{version}``.

REST API Endpoints
------------------

.. list-table:: Milestone 9 Endpoints
   :widths: 35 65
   :header-rows: 1

   * - Endpoint
     - Description
   * - ``GET /api/cameras/{id}/freeze_frame``
     - Returns un-annotated raw video frame (base64) for interactive bounding box selection.
   * - ``POST /api/enroll``
     - Universally enrolls an entity with category, security role, and dual-model features.
   * - ``GET /api/active-learning/queue``
     - Retrieves pending ambiguous detections for review.
   * - ``POST /api/active-learning/{id}/confirm``
     - Promotes candidate crop as a locked ground-truth anchor.
   * - ``POST /api/active-learning/{id}/reassign``
     - Reassigns candidate crop to a different entity.
   * - ``POST /api/active-learning/{id}/enroll-new``
     - Enrolls candidate crop as a new entity profile.
   * - ``POST /api/active-learning/{id}/dismiss``
     - Rejects candidate without altering gallery.
   * - ``GET /api/rsac/categories`` & ``POST``
     - Lists and registers custom categories and badges.
   * - ``GET /api/rsac/rules`` & ``POST``
     - Configures role-based spatial access control zone rules.
   * - ``GET /api/pets/whitelist`` & ``POST``
     - Manages pet perimeter alarm suppression whitelist.
   * - ``GET /api/entities/{id}/versions``
     - Returns descriptor version history and snapshots.
   * - ``POST /api/entities/{id}/rollback/{version}``
     - Restores entity descriptor to an earlier historical version.
