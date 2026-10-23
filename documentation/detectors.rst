Edge AI Detection Architecture
==============================

Overview
--------

Milestone 2 modernizes Intelligent Tracker from legacy Haar cascade classifiers into an extensible, pluggable **Edge AI Detection Architecture**. The architecture supports modern deep learning models (YOLOv8 Nano, YOLO11 Nano) executed via **ONNX Runtime**, with zero heavy framework dependencies (no PyTorch, TensorFlow, or CUDA toolkit required on edge devices).

Key Highlights:
- **Abstract BaseDetector Interface**: Strongly typed contract returning ``Detection(bbox, class_id, confidence, label)`` namedtuples.
- **DetectorFactory Registry**: Decoupled registry supporting runtime lookup by name (``"yolov8"``, ``"yolo11"``, ``"haar"``, ``"mock"``, ``"color"``, ``"face"``, ``"eye"``).
- **Zero-Dependency NumPy Primitives**: Aspect-ratio preserving letterbox resizing, coordinate remapping, and vectorized multi-class Non-Maximum Suppression (NMS).
- **Execution Provider Cascade**: Automatic selection of highest performance runtime provider:
  CUDA -> DirectML (Windows) -> OpenVINO (Intel) -> CoreML (macOS) -> CPU fallback.
- **Full Backwards Compatibility**: Legacy Haar cascades, FaceDetector, EyeDetector, and ColorDetector conform to ``BaseDetector``.
- **Deterministic Mocking**: ``MockDetector`` generates synthetic bounding boxes for headless CI/CD and automated testing without hardware.

Detection Contract
------------------

The detection pipeline standardizes on the ``Detection`` namedtuple:

.. code-block:: python

    Detection = namedtuple('Detection', ['bbox', 'class_id', 'confidence', 'label'])

- ``bbox``: Tuple of ``(x, y, w, h)`` in original image coordinates (integers).
- ``class_id``: Integer identifier of the class (e.g. 0 for person in COCO).
- ``confidence``: Float score between ``0.0`` and ``1.0``.
- ``label``: Human-readable class name string (e.g. ``"person"``).

BaseDetector Interface
----------------------

All detectors inherit from ``BaseDetector``:

.. code-block:: python

    from intelligent_tracker.detectors import BaseDetector, Detection

    class BaseDetector(abc.ABC):
        @abc.abstractmethod
        def detect(self, frame):
            """
            Detect objects in a BGR image frame.

            :param frame: numpy array (H, W, 3) BGR format
            :return: list of Detection(bbox=(x, y, w, h), class_id=int, confidence=float, label=str)
            """
            raise NotImplementedError

DetectorFactory Registry
------------------------

Detectors are registered and retrieved dynamically through ``DetectorFactory``:

.. code-block:: python

    from intelligent_tracker.detectors import DetectorFactory

    # List available detectors
    print(DetectorFactory.available())
    # -> ['cascade', 'color', 'eye', 'face', 'haar', 'mock', 'onnx', 'yolo11', 'yolov8']

    # Instantiate detector
    detector = DetectorFactory.create("yolov8", conf_threshold=0.35, classes=["person"])

OnnxDetector Architecture
-------------------------

The ``OnnxDetector`` class provides lightweight, high-performance Edge AI inference:

Execution Providers Hierarchy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When an ``InferenceSession`` is initialized, ``OnnxDetector`` inspects the host platform and selects the fastest available execution provider:

1. ``CUDAExecutionProvider``: NVIDIA GPU acceleration.
2. ``DmlExecutionProvider`` / ``DirectMLExecutionProvider``: Windows DirectML (AMD, Intel, NVIDIA GPUs).
3. ``OpenVINOExecutionProvider``: Intel CPU / iGPU / NPU acceleration.
4. ``CoreMLExecutionProvider``: Apple Silicon Neural Engine (macOS).
5. ``CPUExecutionProvider``: Universal fallback on all platforms.

Letterbox Preprocessing
~~~~~~~~~~~~~~~~~~~~~~~

Images of arbitrary resolutions are resized to model dimensions (default ``640x640``) preserving aspect ratio with constant border padding (``(114, 114, 114)``):

.. code-block:: python

    padded, scale_ratio, (pad_x, pad_y) = OnnxDetector.letterbox(frame, target_shape=(640, 640))

Vectorized NumPy Non-Maximum Suppression (NMS)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Overlapping bounding boxes are filtered using a vectorized NumPy NMS implementation supporting multi-class offsets to avoid cross-class suppression:

.. code-block:: python

    offset = class_ids[:, None].astype(float) * 4096.0
    boxes_offset = boxes_xyxy + offset
    keep = OnnxDetector.nms_numpy(boxes_offset, confidences, iou_threshold=0.45)

Coordinate Remapping
~~~~~~~~~~~~~~~~~~~~

Bounding box coordinates are mapped back from letterbox canvas space to original image space and strictly clamped to ``[0, orig_w]`` and ``[0, orig_h]``:

.. code-block:: python

    orig_x1 = np.clip((x1 - pad_x) / scale_ratio, 0.0, float(orig_w))
    orig_y1 = np.clip((y1 - pad_y) / scale_ratio, 0.0, float(orig_h))

Model Management
----------------

The ``scripts/download_models.py`` utility handles downloading, mirror failover, and SHA-256 integrity verification:

.. code-block:: powershell

    # Download YOLOv8 Nano (~12.8 MB)
    python scripts/download_models.py --model yolov8n

    # Download YOLO11 Nano (~10.7 MB)
    python scripts/download_models.py --model yolo11n

    # Check status of all models
    python scripts/download_models.py --status

Supported Models:

+------------+---------------+------------------------------------------------------------------+-------------+
| Model Key  | Filename      | SHA-256 Checksum                                                 | Size (MB)   |
+============+===============+==================================================================+=============+
| yolov8n    | yolov8n.onnx  | c03e8dc50385b49f150a8de1b3fa6f3f8a0ba0ce2a458a353179c084f8012f35 | ~12.23 MB   |
+------------+---------------+------------------------------------------------------------------+-------------+
| yolo11n    | yolo11n.onnx  | baeb4c1d6f3bb460689823cc2d40daa31e6156f2517fcd48aab0db9490d9f4e5 | ~10.20 MB   |
+------------+---------------+------------------------------------------------------------------+-------------+

Command-Line Usage
------------------

Run with YOLOv8 on camera 0:

.. code-block:: powershell

    python main.py --detector yolov8 --source 0

Run with YOLO11 on synthetic test frames:

.. code-block:: powershell

    python main.py --detector yolo11 --source synthetic

Filter for person detections only with 0.40 confidence:

.. code-block:: powershell

    python main.py --detector yolov8 --classes person --conf 0.40

Run headless benchmark (30 frames):

.. code-block:: powershell

    python main.py --detector yolov8 --source synthetic --headless --frames 30
