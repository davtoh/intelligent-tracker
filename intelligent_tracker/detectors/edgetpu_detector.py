"""Hardware-accelerated detector using Google Coral Edge TPU / TFLite runtime."""

import os
from typing import Any, Optional
import cv2
import numpy as np

from intelligent_tracker.core import TailItem
from intelligent_tracker.detectors.base import Detection, DetectorFactory
from intelligent_tracker.detectors.core_detector import Detector
from intelligent_tracker.detectors.onnx_detector import COCO_CLASSES


class EdgeTpuDetector(Detector):
    """Hardware-accelerated detector using Google Coral Edge TPU / TFLite runtime.

    Accelerates inference on Raspberry Pi and edge gateways via libedgetpu.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        delegate_path: str = "libedgetpu.so.1",
        use_edgetpu: bool = True,
        labels: Optional[Any] = None,
        **kwargs,
    ):
        super().__init__()
        self.conf_threshold = float(conf_threshold)
        self.iou_threshold = float(iou_threshold)
        self.use_edgetpu = bool(use_edgetpu)
        self.delegate_path = delegate_path
        self.model_path = model_path
        self.labels = labels or {i: name for i, name in enumerate(COCO_CLASSES)}
        self.interpreter = None
        self._init_interpreter()

    def _init_interpreter(self):
        try:
            try:
                from tflite_runtime.interpreter import Interpreter, load_delegate
            except ImportError:
                import tensorflow.lite as tflite

                Interpreter = tflite.Interpreter
                load_delegate = tflite.experimental.load_delegate
        except ImportError:
            self.interpreter = None
            return

        delegates = []
        if self.use_edgetpu:
            try:
                delegates.append(load_delegate(self.delegate_path))
            except Exception:
                pass

        if self.model_path and os.path.isfile(self.model_path):
            try:
                self.interpreter = Interpreter(
                    model_path=self.model_path, experimental_delegates=delegates
                )
                self.interpreter.allocate_tensors()
            except Exception:
                self.interpreter = None

    def _run_tflite_inference(self, frame: np.ndarray) -> list[Detection]:
        input_details = self.interpreter.get_input_details()
        output_details = self.interpreter.get_output_details()
        h, w = input_details[0]["shape"][1:3]
        resized = cv2.resize(frame, (w, h))
        input_data = np.expand_dims(resized, axis=0)
        if input_details[0]["dtype"] == np.float32:
            input_data = (input_data.astype(np.float32) - 127.5) / 127.5
        self.interpreter.set_tensor(input_details[0]["index"], input_data)
        self.interpreter.invoke()

        boxes = self.interpreter.get_tensor(output_details[0]["index"])[0]
        classes = self.interpreter.get_tensor(output_details[1]["index"])[0]
        scores = self.interpreter.get_tensor(output_details[2]["index"])[0]
        orig_h, orig_w = frame.shape[:2]

        detections = []
        for i in range(len(scores)):
            if scores[i] >= self.conf_threshold:
                ymin, xmin, ymax, xmax = boxes[i]
                x = int(xmin * orig_w)
                y = int(ymin * orig_h)
                bw = int((xmax - xmin) * orig_w)
                bh = int((ymax - ymin) * orig_h)
                cid = int(classes[i])
                label = self.labels.get(cid, f"class_{cid}")
                detections.append(
                    Detection(
                        bbox=(x, y, bw, bh),
                        class_id=cid,
                        confidence=float(scores[i]),
                        label=label,
                    )
                )
        return detections

    def detect(self, frame):
        if self.interpreter is None or frame is None:
            return []
        try:
            return self._run_tflite_inference(frame)
        except Exception:
            return []

    def detect_raw_objects(self, frame, mask=None):
        detections = self.detect(frame)
        return [TailItem(bbox=d.bbox) for d in detections]


Detector.register_detector(EdgeTpuDetector)
DetectorFactory.register("edgetpu", EdgeTpuDetector)
DetectorFactory.register("tflite", EdgeTpuDetector)

