RTSP Video Streams & Retail / Occupancy Analytics
==================================================

Overview
--------

Milestone 3 equips Intelligent Tracker with an enterprise-grade video ingestion and computer vision analytics pipeline designed for retail foot traffic, queue dwell time monitoring, security zone surveillance, and smart facility management.

Key Highlights:
- **Non-blocking Threaded RTSP Reader** (``intelligent_tracker.video.VideoSource``):
  - Decoupled frame capture thread preventing network jitter from stalling detection.
  - Bounded queue with zero-latency frame drop on lag.
  - Automatic reconnection with backoff on RTSP stream disruptions.
  - Real-time connection health telemetry (FPS, drop rate %, read counts, uptime).
- **Virtual Tripwires & Polygonal Zone ROIs** (``intelligent_tracker.geometry``):
  - Bidirectional crossing detection with trajectory vector analysis.
  - Polygon containment tests via ``cv2.pointPolygonTest``.
  - Occupancy tracking, dwell time estimation, and automated event emission (``enter``, ``exit``, ``dwell``).
- **Multi-Object Trackers** (``intelligent_tracker.tracker``):
  - ``CentroidTracker``: Multi-stage IoU and Euclidean distance association with zero heavy dependencies.
  - ``SortTracker``: Simple Online and Realtime Tracking with 2D Kalman filtering in pure NumPy.
  - State machine lifecycle (``tentative``, ``confirmed``, ``lost``).
- **Spatial Occupancy Heatmaps** (``intelligent_tracker.analytics.OccupancyHeatmap``):
  - 2D Gaussian density accumulation and continuous temporal decay.
  - False-color overlay blending (``cv2.applyColorMap`` with JET or INFERNO).
  - Snapshot PNG rendering and downsampled CSV matrix exports.
- **YAML Configuration Architecture**:
  - Declarative setup for cameras, tripwires, zones, and detectors (``configs/demo.yaml``, ``configs/retail.yaml``).
- **Headless Video Recording**:
  - Automated export of annotated frames to MP4 (``--output result.mp4``).

Non-blocking Video Reader
-------------------------

The ``VideoSource`` class wraps OpenCV's ``VideoCapture`` in a dedicated background worker thread:

.. code-block:: python

    from intelligent_tracker.video import VideoSource

    # Context manager ensures graceful worker shutdown
    with VideoSource("rtsp://192.168.1.100/stream1", buffer_size=1, auto_reconnect=True) as vs:
        ret, frame = vs.read(timeout=2.0)
        metrics = vs.get_metrics()
        print("FPS: {:.1f}, Drop Rate: {:.2f}%".format(metrics["fps"], metrics["drop_rate_pct"]))

Virtual Tripwires
-----------------

Tripwires detect entities crossing between two points in 2D space and determine crossing direction (``in`` vs ``out``):

.. code-block:: python

    from intelligent_tracker.geometry import Tripwire

    tripwire = Tripwire(line_segment=((100, 240), (540, 240)), name="store_entrance")

    # Update with previous and current track centroids
    event = tripwire.check_crossing(track_id=1, prev_centroid=(200, 230), curr_centroid=(200, 250))
    if event:
        print("Track #{} crossed '{}' going {}".format(event.track_id, event.tripwire_id, event.direction))

Polygonal Zone ROIs
-------------------

Zones define arbitrary polygonal areas of interest to monitor occupancy counts and dwell times:

.. code-block:: python

    from intelligent_tracker.geometry import ZoneROI

    zone = ZoneROI(
        polygon=[(50, 50), (250, 50), (250, 250), (50, 250)],
        name="checkout_queue",
        dwell_threshold=5.0,  # Trigger 'dwell' event after 5 seconds inside
    )

    events = zone.update(active_tracks, timestamp=time.time())
    for ev in events:
        print("Zone {}: Track #{} -> {} (dwell: {:.1f}s)".format(ev.zone_id, ev.track_id, ev.event_type, ev.dwell_time))

Multi-Object Tracking
---------------------

Detectors output individual frame detections. The tracker maintains persistent IDs across frames:

.. code-block:: python

    from intelligent_tracker.tracker import TrackerFactory

    tracker = TrackerFactory.create("centroid", max_disappeared=30, min_hits=2)
    tracks = tracker.update(detections)

    for track_id, track in tracks.items():
        print(f"Track #{track_id}: {track.label} at {track.bbox}, hits: {track.hits}")

Occupancy Heatmaps
------------------

Accumulate customer or visitor dwell locations into a spatial density array:

.. code-block:: python

    from intelligent_tracker.analytics import OccupancyHeatmap

    heatmap = OccupancyHeatmap(width=640, height=480, decay_rate=0.998, radius=25)
    heatmap.update(tracks)

    # Render blended overlay on current video frame
    annotated_frame = heatmap.draw(frame, alpha=0.45)

    # Export CSV summary for business intelligence
    heatmap.export_csv("analytics/heat_matrix.csv")

Configuration Files
-------------------

YAML templates configure the entire analytics pipeline declaratively:

.. code-block:: yaml

    # configs/demo.yaml
    video:
      source: synthetic
      resolution: [640, 480]
      framerate: 30

    detector:
      model: mock
      confidence: 0.25

    tracker:
      type: centroid
      max_disappeared: 30
      min_hits: 2

    analytics:
      tripwires:
        - name: main_corridor
          line: [[100, 240], [540, 240]]
          bidirectional: true

      zones:
        - name: lounge_zone
          polygon: [[40, 40], [280, 40], [280, 220], [40, 220]]
          dwell_threshold: 3.0

CLI Usage
---------

.. code-block:: powershell

    # Run demo config in headless mode with video export
    .\.venv\Scripts\python.exe main.py --config configs/demo.yaml --headless --frames 100 --output output.mp4

    # Run with YOLOv8 on an RTSP stream
    .\.venv\Scripts\python.exe main.py --detector yolov8 --source rtsp://192.168.1.100/stream1 --config configs/retail.yaml
