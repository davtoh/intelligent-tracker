.. intelligent-tracker documentation master file.

Intelligent Tracker Documentation
=================================

**Intelligent Tracker** is a modular, high-performance edge computer vision pipeline designed for real-time multi-object tracking, spatial analytics, Person/Vehicle Re-Identification (Re-ID), automated event alerting, and interactive web dashboard monitoring.

System Architecture
-------------------

.. code-block:: text

    +-------------------+      +-------------------+      +-------------------+
    |   Video Source    | ---> | Deep Learning     | ---> | Multi-Object      |
    | (Webcam/RTSP/Pi)  |      | Detectors (YOLO/  |      | Tracker           |
    |                   |      | SSD/EdgeTPU/HOG)  |      | (ByteTrack/SORT)  |
    +-------------------+      +-------------------+      +-------------------+
                                                                    |
                                                                    v
    +-------------------+      +-------------------+      +-------------------+
    | Web Dashboard &   | <--- | Event Bus &       | <--- | PipelineEngine &  |
    | Operator CLI      |      | WorldGraph /      |      | Spatial Analytics |
    | (FastAPI, ctl)    |      | Alert Rule Engine |      | (Zones, Tripwires)|
    +-------------------+      +-------------------+      +-------------------+
              ^                          ^                          ^
              |                          |                          |
              +--------------------------+--------------------------+
                                         |
                               +-------------------+
                               | Semantic Memory & |
                               | Re-ID (OSNet /    |
                               | FTS5 / SQLite)    |
                               +-------------------+

Documentation Contents
----------------------

.. toctree::
   :maxdepth: 2
   :caption: Core Pipeline & Modules:

   intelligent_tracker
   detectors
   analytics
   reid
   events
   memory_and_world_query

.. toctree::
   :maxdepth: 2
   :caption: Dashboard, VMS & Spatial Studio:

   dashboard
   vms
   camera_management
   scenario_studio
   artifact_and_face_intelligence
   deployment

.. toctree::
   :maxdepth: 2
   :caption: Enterprise Cloud Integration:

   enterprise_hub_integration

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
