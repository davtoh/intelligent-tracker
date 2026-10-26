.. _vms:

Multi-Camera VMS & Video Source Manager
=======================================

The **Multi-Camera Video Management System (VMS)** transforms Intelligent Tracker into an enterprise-grade,
distributed surveillance and retail analytics platform. It provides dynamic multi-stream lifecycle management,
dual hardware/LAN camera auto-discovery, interactive video scrubbing, and portable system state migration.

Architecture Overview
---------------------

.. code-block:: text

    +-----------------------------------------------------------------------------------+
    |                              Dynamic CameraPool                                   |
    |  +--------------------+   +--------------------+   +--------------------+         |
    |  | StreamManager #1   |   | StreamManager #2   |   | StreamManager #N   |         |
    |  | (USB Webcam)       |   | (RTSP Tapo HD)     |   | (Uploaded MP4)     |         |
    |  +--------------------+   +--------------------+   +--------------------+         |
    +-----------------------------------------------------------------------------------+
              |                           |                           |
              v                           v                           v
    +--------------------+      +--------------------+      +--------------------+
    |  /stream/cam_01    |      |  /stream/cam_02    |      |  /stream/cam_N     |
    +--------------------+      +--------------------+      +--------------------+
              \                           |                           /
               \                          |                          /
                v                         v                         v
    +-----------------------------------------------------------------------------------+
    |                    FastAPI Multi-Camera VMS Dashboard                             |
    |  - 1x1 Focused View (Single Cam Canvas + Click-to-Tag + Heatmap)                  |
    |  - 2x2 Quad Multi-View Grid                                                       |
    |  - 3x3 Matrix Multi-View Grid                                                     |
    |  - Auto-Discovery Modal (USB + ONVIF UDP 3702 + LAN RTSP 554/8554)                |
    |  - Video Studio (Frame-stepping scrubber, 1x/2x/4x/8x playback, Batch Analytics)  |
    |  - Full System State Snapshot (.zip export / import)                              |
    +-----------------------------------------------------------------------------------+

Key Capabilities
----------------

1. **Dual Hardware & Network Auto-Discovery**:
   - **Local USB Webcams**: Physical hardware probing across video capture indices using DirectShow (Windows) and V4L2 (Linux).
   - **ONVIF WS-Discovery**: Broadcasts standard XML SOAP probe messages over UDP port 3702 to ``239.255.255.250``. Detects Network Video Transmitters (NVTs) and parses XAddrs.
   - **LAN Subnet RTSP Scanner**: High-speed concurrent TCP socket scanning across ports 554, 8554, and 8000 for open RTSP endpoints.
   - **One-Click Diagnostics**: Live connection test returning decoded resolution, FPS, and an encoded base64 JPEG preview snapshot.

2. **Vendor RTSP Presets & Credential Builder**:
   Built-in URL builders with automatic URL-encoding for complex passwords containing special characters (``@``, ``#``, ``:``):

   - **Hikvision**: ``rtsp://{user}:{pass}@{ip}:554/Streaming/Channels/{channel}01``
   - **TP-Link Tapo**: ``rtsp://{user}:{pass}@{ip}:554/stream1`` (HD) or ``/stream2`` (SD)
   - **EZVIZ**: ``rtsp://admin:{verification_code}@{ip}:554/h264/ch{channel}/main``
   - **Dahua / Imou**: ``rtsp://{user}:{pass}@{ip}:554/cam/realmonitor?channel={channel}&subtype=0``
   - **Generic RTSP**: ``rtsp://{user}:{pass}@{ip}:{port}/live``

3. **Dynamic Stream Orchestration (CameraPool)**:
   - Hot-add, configure, toggle, and remove streams at runtime without server restarts.
   - Automatic boot restoration: on launch, all saved cameras in ``configs/cameras.json`` are restored into active background pipelines.
   - Thread-safe isolation: each stream runs in an independent worker thread.

4. **Responsive Multi-Grid Switcher**:
   - **1x1 Focused View**: High-resolution interactive stream with real-time bounding box canvas, click-to-tag entity enrollment, and spatial density heatmap overlay.
   - **2x2 Quad View**: 4-camera concurrent monitoring matrix with individual status indicators, FPS badges, and active track counters.
   - **3x3 Matrix View**: 9-camera operational overview for control room monitoring. Clicking any tile instantly switches to focused 1x1 view.

5. **Video Studio & Playback Scrubber**:
   - Upload recorded footage (``.mp4``, ``.avi``, ``.mkv``, ``.mov``) via web UI or REST API into ``data/videos/``.
   - Precise frame-stepping controls (``< -1 Frame``, ``> +1 Frame``) and variable playback rates (1x, 2x, 4x, 8x).
   - One-click registration of recorded video as an active live camera feed.
   - One-click offline occurrence indexing via ``BatchVideoIndexer`` generating detection tallies, dwell times, and sighting records in ``TrackerDB``.

6. **State Persistence, Auto-Restore & Full Import/Export**:
   - **One-Click Snapshot Export**: Packages SQLite database (``tracker.db``), face and entity crops (``data/crops/``), and configurations (``configs/``) into a portable, versioned ``.zip`` archive with SHA-256 checksums.
   - **Full System Migration**: Port entire system configurations between edge nodes (e.g. Workstation -> Raspberry Pi / Intel NUC) with Zip-Slip path traversal protection and schema validation.
   - **CLI Tooling**:

     .. code-block:: bash

        # Export system snapshot
        python -m intelligent_tracker.backup --export backup.zip

        # Inspect backup manifest without extracting
        python -m intelligent_tracker.backup --info backup.zip

        # Import and restore system state
        python -m intelligent_tracker.backup --import backup.zip

REST API Reference
------------------

Camera Management & Discovery
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 20 25 55
   :header-rows: 1

   * - Method
     - Endpoint
     - Description
   * - ``GET``
     - ``/api/cameras``
     - List all configured cameras with live telemetry (status, FPS, tracks, resolution).
   * - ``POST``
     - ``/api/cameras``
     - Hot-add a new camera stream dynamically to the CameraPool.
   * - ``GET``
     - ``/api/cameras/{id}``
     - Get configuration and health metrics for a specific camera channel.
   * - ``PUT``
     - ``/api/cameras/{id}``
     - Update display name, RTSP source, or algorithm parameters.
   * - ``DELETE``
     - ``/api/cameras/{id}``
     - Stop pipeline and remove camera channel from pool and disk.
   * - ``POST``
     - ``/api/cameras/{id}/toggle``
     - Enable or pause a camera stream.
   * - ``GET``
     - ``/api/cameras/discover``
     - Probe USB webcams, ONVIF WS-Discovery, and local subnet RTSP ports.
   * - ``POST``
     - ``/api/cameras/test``
     - Test connectivity to any video source and return live preview snapshot.
   * - ``GET``
     - ``/api/cameras/presets``
     - Retrieve vendor RTSP URL builder templates.

Video Studio & Scrubber Endpoints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 20 25 55
   :header-rows: 1

   * - Method
     - Endpoint
     - Description
   * - ``GET``
     - ``/api/videos``
     - List uploaded recording files in ``data/videos/``.
   * - ``POST``
     - ``/api/videos/upload``
     - Upload ``.mp4``, ``.avi``, or ``.mkv`` recording via multipart form data.
   * - ``DELETE``
     - ``/api/videos/{name}``
     - Delete recording file from disk.
   * - ``POST``
     - ``/api/videos/{name}/add_as_camera``
     - Register uploaded video file as an active camera stream in the pool.
   * - ``POST``
     - ``/api/videos/{name}/analyze``
     - Run offline batch entity and sighting occurrence analytics.
   * - ``GET``
     - ``/videos/{name}``
     - Stream video file supporting HTML5 seeking and range requests.

System State Persistence & Backup Endpoints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 20 25 55
   :header-rows: 1

   * - Method
     - Endpoint
     - Description
   * - ``GET``
     - ``/api/backup/export``
     - Download complete portable system snapshot ``.zip`` archive.
   * - ``POST``
     - ``/api/backup/import``
     - Upload and restore full database, crops, and configurations from snapshot.
