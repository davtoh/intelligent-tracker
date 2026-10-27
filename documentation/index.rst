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
    | Web Dashboard     | <--- | Event Bus &       | <--- | Spatial Analytics |
    | (FastAPI, Canvas, |      | Alert Rule Engine |      | (Zones, Tripwires,|
    | MJPEG, WebSocket) |      | (MQTT/Telegram)   |      | Dwell, Heatmaps)  |
    +-------------------+      +-------------------+      +-------------------+
              ^                          ^                          ^
              |                          |                          |
              +--------------------------+--------------------------+
                                         |
                               +-------------------+
                               | Person / Vehicle  |
                               | Re-Identification |
                               | (OSNet / SQLite)  |
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

.. toctree::
   :maxdepth: 2
   :caption: Dashboard, VMS & Spatial Studio:

   dashboard
   vms
   scenario_studio
   deployment

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
