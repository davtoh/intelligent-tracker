.. _camera_management:

Hardware Camera Discovery & Resource Management
===============================================

Intelligent Tracker includes comprehensive hardware camera discovery, exclusive lock management, process diagnostics, and multi-consumer proxying. This guide explains how physical video capture devices are discovered, how hardware contention is resolved across processes and platforms, and how to operate the management tooling.

Architecture & Device Contention
--------------------------------

Physical USB cameras, webcams, and capture cards interface with operating system video subsystems:

- **Windows**: Microsoft DirectShow (``CAP_DSHOW``) or Media Foundation (``CAP_MSMF``)
- **Linux**: Video4Linux2 (``CAP_V4L2``)
- **macOS**: AVFoundation (``CAP_AVFOUNDATION``)

Under Windows DirectShow and Linux V4L2, physical capture devices operate in **exclusive mode**: only a single OS process or thread handle can capture from the camera pin at any given moment.

.. code-block:: text

    +-------------------------------------------------------------------------------+
    |                          Exclusive Hardware Pin Lock                          |
    |                                                                               |
    |  +--------------------+                   +--------------------------------+  |
    |  | Physical USB Cam   | <=== LOCKED ===== | Python PID 27368 (Uvicorn /    |  |
    |  | (Index #2, HD Pro) |                   |  OpenCV VideoCapture)          |  |
    |  +--------------------+                   +--------------------------------+  |
    |            |                                                                  |
    |            x (Attempted open fails with cap.isOpened() == False)              |
    |            |                                                                  |
    |  +--------------------+                                                       |
    |  | main.py / VMS GUI  |                                                       |
    |  +--------------------+                                                       |
    +-------------------------------------------------------------------------------+

When a process terminates abruptly without cleanly calling ``cv2.VideoCapture.release()``, the OS handle may remain bound to an orphaned background worker process. Subsequent capture attempts fail with:

.. code-block:: text

    ✗ Connection Failed: Could not open video capture device or RTSP stream

Intelligent Tracker provides automated diagnostics to locate the holding PID, terminate orphaned workers, test capture pins, and enable multi-consumer stream proxying.

Automated Hardware Discovery
----------------------------

The ``intelligent_tracker.camera_device`` module inspects attached video capture devices and automatically distinguishes physical webcams from virtual or broadcast devices:

1. **Hardware Inspection**:
   DirectShow and V4L2 system APIs query device names, friendly strings, and default capture resolutions (e.g. 1920x1080 vs. 640x480).
2. **Virtual Device Filtering**:
   Software broadcast cameras such as *OBS Virtual Camera*, *Unity Video Capture*, or software loopbacks are categorized appropriately, allowing physical hardware to be prioritized.
3. **Friendly Source Resolution**:
   The ``--source`` flag in ``main.py`` supports intelligent string matching:

   - ``--source real``: Auto-detects the first operational physical USB/webcam hardware device (skipping virtual loopback devices).
   - ``--source gopro`` / ``--source webcam``: Matches connected device names containing "gopro" or "webcam" case-insensitively.
   - ``--source obs``: Matches software capture devices containing "obs".
   - ``--source 0``, ``--source 1``, etc.: Standard numerical index binding.
   - ``--source synthetic``: Generates animated synthetic test frames without hardware.

Camera Manager Tool (CLI)
-------------------------

The CLI utility ``scripts/camera_manager.py`` (powered by ``intelligent_tracker.camera_tool``) provides administrative inspection and remediation commands.

Pre-Run Verification Diagnostic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Check the status of all video capture devices and running camera workers:

.. code-block:: bash

    python scripts/camera_manager.py --status

Example output:

.. code-block:: text

    ================================================================================
    Intelligent Tracker - Hardware Camera Status & Process Manager
    ================================================================================
    [INFO] Probing video capture devices (indices 0..5)...

    --------------------------------------------------------------------------------
    CONNECTED VIDEO CAPTURE DEVICES:
    --------------------------------------------------------------------------------
    Index  Device Name                  Resolution   FPS    Type      Status
    --------------------------------------------------------------------------------
    0      OBS Virtual Camera           1920x1080    -      Virtual   AVAILABLE
    1      OBS Virtual Camera           1920x1080    -      Virtual   AVAILABLE
    2      USB Camera (GoPro / Webcam)  1920x1080    -      Hardware  AVAILABLE
    --------------------------------------------------------------------------------

    --------------------------------------------------------------------------------
    ACTIVE PYTHON CAMERA WORKER PROCESSES:
    --------------------------------------------------------------------------------
    PID 14208 | [PYTHON] | 114.2 MB | ...\python.exe -m uvicorn dashboard.app:app

Targeted Camera Release
~~~~~~~~~~~~~~~~~~~~~~~

If a specific camera index is blocked or failing to open, force a release on that device index:

.. code-block:: bash

    # Release device index 2
    python scripts/camera_manager.py --release-camera 2

    # Force release even if in use
    python scripts/camera_manager.py --release-camera 2 --force

Targeted Process Termination
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If a specific background process PID is holding a camera handle:

.. code-block:: bash

    # Gracefully terminate PID 27368
    python scripts/camera_manager.py --kill-pid 27368

    # Force terminate PID 27368 immediately (SIGKILL / Process.kill)
    python scripts/camera_manager.py --kill-pid 27368 --force

Bulk Cleanup of Orphaned Workers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To release all probe handles and terminate all orphaned Python camera workers in one step:

.. code-block:: bash

    python scripts/camera_manager.py --release --kill-orphans

JSON Telemetry Output
~~~~~~~~~~~~~~~~~~~~~

For programmatic integration or monitoring scripts:

.. code-block:: bash

    python scripts/camera_manager.py --status --json

Multi-Consumer Shared Stream Proxy
----------------------------------

Because physical capture devices enforce single-process hardware locks, running multiple applications (e.g. the FastAPI Web Dashboard and a local ``main.py`` tracking script) against the same hardware index simultaneously results in an access conflict.

To share a single camera across multiple consumers, use the **Dashboard Loopback Stream Proxy**:

1. **Dashboard Acquisition**:
   The FastAPI dashboard acts as the primary capture agent, acquiring the physical camera stream (e.g. ``cam_01`` mapped to index 2).
2. **MJPEG Stream Broadcast**:
   The dashboard exposes a high-efficiency MJPEG feed at ``/api/v1/streams/<cam_id>/feed``.
3. **Multi-Consumer Access**:
   Any number of external processes or containers consume from the HTTP endpoint simultaneously:

.. code-block:: text

    +--------------------+
    | Physical USB Cam   |
    | (Index #2)         |
    +--------------------+
              |
              v (DirectShow / V4L2 capture)
    +-----------------------------------------+
    | FastAPI Web Dashboard (StreamManager)   |
    | Endpoint: /api/v1/streams/cam_01/feed   |
    +-----------------------------------------+
              |                    |
              | (HTTP Stream)      | (HTTP Stream via host gateway)
              v                    v
    +--------------------+  +--------------------------------+
    | Local main.py      |  | Dockerized Analytics Worker    |
    | Tracking Script    |  | (host.docker.internal:8000)    |
    +--------------------+  +--------------------------------+

To consume the shared stream in ``main.py``:

.. code-block:: bash

    # From the local host machine
    python main.py --source http://localhost:8000/api/v1/streams/cam_01/feed --detector yolov8

    # From within a Docker container
    python main.py --source http://host.docker.internal:8000/api/v1/streams/cam_01/feed --detector yolov8

Scenario Combinations Matrix
----------------------------

+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
| Scenario / Intent                   | Key Parameters                                     | Runnable Command                                                                                   |
+=====================================+====================================================+====================================================================================================+
| **Camera & Process Audit**          | ``--status``                                       | ``python scripts/camera_manager.py --status``                                                      |
+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
| **Release Blocked Camera Index**    | ``--release-camera <INDEX>``                       | ``python scripts/camera_manager.py --release-camera 2``                                            |
+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
| **Force Release Blocked Camera**    | ``--release-camera <INDEX> --force``               | ``python scripts/camera_manager.py --release-camera 2 --force``                                    |
+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
| **Kill Orphaned Worker PID**        | ``--kill-pid <PID>``                               | ``python scripts/camera_manager.py --kill-pid 27368``                                              |
+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
| **Force Kill Orphaned Worker PID**  | ``--kill-pid <PID> --force``                       | ``python scripts/camera_manager.py --kill-pid 27368 --force``                                      |
+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
| **Full Emergency Cleanup**          | ``--release --kill-orphans``                       | ``python scripts/camera_manager.py --release --kill-orphans``                                      |
+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
| **Physical Webcam Auto-Detect**     | ``--source real``                                  | ``python main.py --detector yolov8 --source real --classes person --conf 0.40``                    |
+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
| **Target Device by Name**           | ``--source gopro`` / ``--source usb``              | ``python main.py --detector yolov8 --source gopro --classes person --conf 0.40``                   |
+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
| **Multi-Consumer Local Stream**     | ``--source http://localhost:8000/...``             | ``python main.py --source http://localhost:8000/api/v1/streams/cam_01/feed --detector yolov8``     |
+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
| **Multi-Consumer Docker Stream**    | ``--source http://host.docker.internal:8000/...``   | ``python main.py --source http://host.docker.internal:8000/api/v1/streams/cam_01/feed``           |
+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
| **JSON Status Probe (API / Bash)**  | ``--status --json``                                | ``python scripts/camera_manager.py --status --json``                                               |
+-------------------------------------+----------------------------------------------------+----------------------------------------------------------------------------------------------------+
