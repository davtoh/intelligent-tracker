========================================================================
Object Identity Gallery, Visual Re-ID & Sighting Database
========================================================================

The **Re-Identification (Re-ID)** architecture provides cross-session entity recognition,
visual feature embeddings, a thread-safe SQLite entity gallery, interactive screen selection,
and offline video recording occurrence analytics.

Key Components
==============

1. Persistent SQLite Database (``TrackerDB``)
---------------------------------------------
Zero-configuration embedded local database (``data/tracker.db``) managing:

- **``entities``**: Registered subjects, vehicles, or assets with categorisation (e.g. ``"vip"``, ``"staff"``, ``"visitor"``, ``"vehicle"``).
- **``entity_signatures``**: Multi-dimensional visual embeddings stored as raw BLOBs alongside representative thumbnail crop paths.
- **``sightings``**: Complete chronological audit trail capturing track IDs, camera sources, timestamps, zone locations, bounding boxes, and recognition confidence scores.
- **Indexed Lookups**: Compound indexes on ``(entity_id, timestamp)`` and ``(source, timestamp)`` for sub-millisecond timeline queries.

2. Visual Feature Descriptors (``BaseFeatureExtractor``)
--------------------------------------------------------
Two primary feature extraction backends:

- **``OnnxReIDExtractor``**:
  Deep visual embeddings via lightweight ONNX models (e.g. ``osnet_x0_25.onnx``, ~907 KB, 512-d embeddings).
  Executes with automatic hardware acceleration cascade: CUDA -> DirectML -> OpenVINO -> CoreML -> CPU.
- **``ColorHistogramExtractor``**:
  Ultra-lightweight spatial HSV color descriptor (pure NumPy/OpenCV, zero neural network overhead, sub-millisecond on Raspberry Pi CPU).
  Divides crops into vertical spatial cells (head/torso/legs) to capture clothing/vehicle color structure.
- **``MockFeatureExtractor``**:
  Deterministic synthetic feature generator for automated CI and headless testing.

3. Gallery Matcher & Re-Appearance Engine (``GalleryMatcher``)
--------------------------------------------------------------
Coordinates real-time multi-object tracks with long-term SQLite entity gallery:

- **Temporal Feature Pooling**: Averages feature embeddings across high-confidence frames for smooth, stable identity signatures.
- **Vectorized Batch Cosine Similarity**: High-speed matrix-vector multiplication against all enrolled gallery signatures simultaneously.
- **Debounced Sighting Audit Trail**: Records verified entity sightings into the database at configurable intervals without redundant per-frame writes.
- **Dynamic Track Decoration**: Automatically annotates confirmed tracks with entity IDs, names, categories, and similarity confidence.

4. Interactive Tagging Studio (``InteractiveController``)
---------------------------------------------------------
Enables real-time screen inspection, entity enrollment, and ROI definition:

- **Screen Selection**: Left-click any bounding box to select and inspect target telemetry (speed, dwell duration, track ID, Re-ID status).
- **Entity Enrollment Prompt**: Press ``'e'`` to enroll the selected target directly into the gallery, automatically capturing thumbnail crops and extracting feature vectors.
- **Interactive ROI Drawing**: Press ``'t'`` to draw virtual tripwires or ``'z'`` to draw polygonal zones directly on the live/paused video window.

5. Offline Video Recording Indexer (``VideoIndexer``)
-----------------------------------------------------
Batch processing engine for recorded video files (``.mp4``, ``.avi``, ``.mkv``):

- Fast-forward processing with frame sampling (``--sample-rate N``).
- Automated detection, tracking, feature extraction, Re-ID matching, and database logging.
- Occurrence Reports:
  - **Sighting Timeline**: Chronological log of appearances per entity.
  - **Dwell Time & Visit Frequency**: Total observed duration, first seen, and last seen.
  - **Zone Journey**: Spatial movement across monitored zones.
  - Exports to console summary tables, JSON, and CSV formats.

CLI Usage Examples
==================

Live Tracking with Visual Re-ID:
--------------------------------
.. code-block:: bash

   # Run with lightweight spatial color histogram Re-ID
   python main.py --detector yolov8 --reid color --db data/tracker.db

   # Run with deep ONNX OSNet Re-ID model
   python main.py --detector yolov8 --reid onnx --db data/tracker.db

Interactive Tagging Studio:
---------------------------
.. code-block:: bash

   # Launch interactive enrollment and inspection GUI
   python -m intelligent_tracker.interactive --source 0 --db data/tracker.db

Offline Video Indexing & Analytics Reporting:
---------------------------------------------
.. code-block:: bash

   # Index recorded video footage and output occurrence report
   python -m intelligent_tracker.batch --video footage.mp4 --db data/tracker.db --report

   # Fast-forward indexing (sample every 3rd frame) and export audit trail
   python -m intelligent_tracker.batch --video footage.mp4 --db data/tracker.db --sample-rate 3 --export-json audit.json --export-csv audit.csv
