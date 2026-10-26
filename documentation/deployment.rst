.. _deployment:

Edge Deployment & Packaging Guide
==================================

This guide details deployment options for **Intelligent Tracker** on resource-constrained edge devices
(such as Raspberry Pi 4/5, Coral Dev Board, NVIDIA Jetson, Intel NUC) and production Linux servers.

Overview
--------

Intelligent Tracker supports several deployment topologies:

1. **Systemd Services**: Native background daemons managed by systemd on Raspberry Pi OS Bookworm (Debian 12) or Ubuntu 24.04 LTS.
2. **Docker Containers**: Multi-stage lightweight OCI container images targeting ``linux/arm64`` and ``linux/amd64``.
3. **Docker Compose**: Multi-service stack orchestrating the Tracker engine, Web Dashboard, and Mosquitto MQTT broker.

Hardware Acceleration
---------------------

Google Coral Edge TPU
~~~~~~~~~~~~~~~~~~~~~

The ``EdgeTpuDetector`` class leverages Google Coral USB or M.2 Edge TPUs for high-throughput, low-power object detection:

1. Install the Coral Edge TPU runtime on the host:

   .. code-block:: bash

      echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
      curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/coral-edgetpu.gpg
      sudo apt-get update && sudo apt-get install -y libedgetpu1-std

2. Configure detector in your pipeline configuration:

   .. code-block:: yaml

      detection:
        framework: edgetpu
        model: models/ssd_mobilenet_v2_coco_quant_postprocess_edgetpu.tflite
        device: ":0"
        confidence_threshold: 0.5

Intel OpenVINO & ONNX Runtime
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For x86_64 edge devices (e.g., Intel NUC, industrial PCs):

.. code-block:: yaml

   reid:
     model_type: onnx
     model_path: models/osnet_x0_25_msmt17.onnx
     execution_provider: OpenVINOExecutionProvider  # or CPUExecutionProvider

Raspberry Pi Camera & libcamera
-------------------------------

Raspberry Pi OS Bookworm (64-bit) replaced the legacy V4L2 stack with **libcamera**. Intelligent Tracker natively discovers and connects to Pi Camera Modules 2, 3, and HQ cameras using GStreamer:

.. code-block:: yaml

   video:
     source: "libcamerasrc ! video/x-raw,width=1280,height=720,framerate=30/1 ! videoconvert ! appsink"
     api_preference: gstreamer

Or simply provide ``source: "libcamera"`` for automatic pipeline generation.

OpenCV Installation Script
--------------------------

Use ``install_opencv.sh`` to install OpenCV on Debian/Ubuntu edge systems:

.. code-block:: bash

   # Option 1: Fast installation from system package manager (Debian Bookworm / Ubuntu 24.04)
   ./install_opencv.sh --apt

   # Option 2: Pre-compiled wheels via pip inside a virtual environment
   ./install_opencv.sh --pip

   # Option 3: Compile from source with Coral/GStreamer flags (RPi 4/5, ~35 minutes)
   ./install_opencv.sh --source

Systemd Service Deployment
--------------------------

To run Intelligent Tracker as an autonomous daemon that launches on system boot:

1. Copy service definitions:

   .. code-block:: bash

      sudo cp deployment/intelligent-tracker.service /etc/systemd/system/
      sudo cp deployment/intelligent-tracker-dashboard.service /etc/systemd/system/

2. Ensure the user belongs to the ``video`` group for hardware camera access:

   .. code-block:: bash

      sudo usermod -a -G video pi

3. Reload systemd daemon and enable services:

   .. code-block:: bash

      sudo systemctl daemon-reload
      sudo systemctl enable intelligent-tracker.service
      sudo systemctl enable intelligent-tracker-dashboard.service
      sudo systemctl start intelligent-tracker.service
      sudo systemctl start intelligent-tracker-dashboard.service

4. Monitor system logs:

   .. code-block:: bash

      journalctl -u intelligent-tracker.service -f
      journalctl -u intelligent-tracker-dashboard.service -f

Docker Container Deployment
---------------------------

Multi-Architecture Build
~~~~~~~~~~~~~~~~~~~~~~~~

Pre-built Dockerfiles are provided for arm64 and amd64 architectures:

- ``Dockerfile.arm64``: Debian Bookworm base with GStreamer and libcamera support.
- ``Dockerfile.amd64``: Optimized Intel/AMD runtime with OpenVINO hooks.
- ``Dockerfile``: Multi-arch target building on Python 3.11-slim.

To build manually:

.. code-block:: bash

   # Build for ARM64 (Raspberry Pi 4/5)
   docker build -f Dockerfile.arm64 -t intelligent-tracker:latest-arm64 .

   # Build for AMD64
   docker build -f Dockerfile.amd64 -t intelligent-tracker:latest-amd64 .

Docker Compose Stack
~~~~~~~~~~~~~~~~~~~~

Run the complete multi-service edge stack with one command:

.. code-block:: bash

   docker compose up -d

This spins up:

- **tracker**: Core video pipeline, detector, tracker, Re-ID matcher, and event emitter.
- **dashboard**: FastAPI Web Dashboard serving live MJPEG stream and WebSockets on port ``8000``.
- **mosquitto**: Eclipse Mosquitto MQTT message broker on port ``1883`` for IoT integration.

To stop the services:

.. code-block:: bash

   docker compose down
