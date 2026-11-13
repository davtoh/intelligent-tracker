"""High-performance Edge AI Object Detector using ONNX Runtime."""

import os
from typing import Any, Optional
import cv2
import numpy as np

from intelligent_tracker.core import TailItem
from intelligent_tracker.detectors.base import Detection, DetectorFactory
from intelligent_tracker.detectors.coco_classes import COCO_CLASSES
from intelligent_tracker.detectors.core_detector import Detector

PRIORITY_PROVIDERS = [
    "CUDAExecutionProvider",
    "DmlExecutionProvider",
    "DirectMLExecutionProvider",
    "OpenVINOExecutionProvider",
    "CoreMLExecutionProvider",
    "CPUExecutionProvider",
]


def resolve_model_path(model_path: Optional[str]) -> str:
    """Resolve ONNX model file path from candidate directories or download helper."""
    if model_path is None:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        repo_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
        candidate = os.path.join(repo_root, "models", "yolov8n.onnx")
        if not os.path.isfile(candidate):
            try:
                from intelligent_tracker.detectors.model_loader import ensure_model

                candidate = ensure_model("yolov8n")
            except Exception:
                pass
        model_path = candidate

    resolved = os.path.abspath(model_path)
    if not os.path.isfile(resolved):
        raise IOError(
            f"ONNX model file not found at: {resolved}. Please run scripts/download_models.py"
        )
    return resolved


def resolve_labels(labels: Optional[Any]) -> dict[int, str]:
    """Map class IDs to descriptive label strings."""
    if labels is None:
        return {i: name for i, name in enumerate(COCO_CLASSES)}
    if isinstance(labels, (list, tuple)):
        return {i: name for i, name in enumerate(labels)}
    if isinstance(labels, dict):
        return labels
    raise TypeError("labels must be a list, tuple, or dict")


def resolve_classes(classes: Optional[Any], label_map: dict[int, str]) -> Optional[set[int]]:
    """Convert requested filter class names or indices to integer IDs."""
    if classes is None:
        return None
    resolved = set()
    for c in classes:
        if isinstance(c, int):
            resolved.add(c)
        elif isinstance(c, (str, bytes)):
            for cid, lbl in label_map.items():
                if lbl.lower() == str(c).lower():
                    resolved.add(cid)
    return resolved


def get_available_execution_providers(requested=None) -> list[str]:
    """Return filtered list of execution providers supported in runtime environment."""
    import onnxruntime as ort

    if requested:
        if isinstance(requested, (str, bytes)):
            requested = [requested]
        return list(requested)
    available = set(ort.get_available_providers())
    providers = [p for p in PRIORITY_PROVIDERS if p in available]
    return providers if providers else ["CPUExecutionProvider"]


def resolve_input_size(shape, custom_input_size):
    """Determine (height, width) dimensions for model input tensor."""
    if custom_input_size is not None:
        if isinstance(custom_input_size, (int, float)):
            return int(custom_input_size), int(custom_input_size)
        if isinstance(custom_input_size, (tuple, list)) and len(custom_input_size) == 2:
            return int(custom_input_size[1]), int(custom_input_size[0])
    if len(shape) == 4:
        h = shape[2] if isinstance(shape[2], int) and shape[2] > 0 else 640
        w = shape[3] if isinstance(shape[3], int) and shape[3] > 0 else 640
        return h, w
    return 640, 640


def letterbox(frame, target_shape=(640, 640), fill_value=(114, 114, 114)):
    """Resize image and pad to target_shape while preserving aspect ratio."""
    target_h, target_w = target_shape
    orig_h, orig_w = frame.shape[:2]
    r = min(float(target_w) / float(orig_w), float(target_h) / float(orig_h))
    new_w = int(round(orig_w * r))
    new_h = int(round(orig_h * r))
    pad_x = (target_w - new_w) / 2.0
    pad_y = (target_h - new_h) / 2.0

    if (orig_w, orig_h) != (new_w, new_h):
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    else:
        resized = frame

    top = int(round(pad_y - 0.1))
    bottom = int(round(pad_y + 0.1))
    left = int(round(pad_x - 0.1))
    right = int(round(pad_x + 0.1))
    padded = cv2.copyMakeBorder(
        resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=fill_value
    )
    return padded, r, (pad_x, pad_y)


def nms_numpy(boxes, scores, iou_threshold=0.45):
    """Pure NumPy Non-Maximum Suppression algorithm."""
    if len(boxes) == 0:
        return []
    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        union = areas[i] + areas[order[1:]] - inter
        iou = np.where(union > 0, inter / np.maximum(union, 1e-6), 0.0)
        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]
    return keep


class OnnxDetector(Detector):
    """High-performance Edge AI Object Detector using ONNX Runtime.

    Supports YOLOv8, YOLO11, and custom ONNX detection models with zero external dependencies.
    """

    PRIORITY_PROVIDERS = PRIORITY_PROVIDERS

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        classes: Optional[Any] = None,
        labels: Optional[Any] = None,
        input_size: Optional[Any] = None,
        providers: Optional[Any] = None,
    ):
        super().__init__()
        import onnxruntime as ort

        self.model_path = resolve_model_path(model_path)
        self.conf_threshold = float(conf_threshold)
        self.iou_threshold = float(iou_threshold)
        self.custom_input_size = input_size
        self.labels = resolve_labels(labels)
        self.classes = resolve_classes(classes, self.labels)
        self.providers = get_available_execution_providers(providers)

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            self.model_path, sess_options=opts, providers=self.providers
        )
        self.active_provider = self.session.get_providers()[0]
        self.input_node = self.session.get_inputs()[0]
        self.input_name = self.input_node.name
        self.output_names = [o.name for o in self.session.get_outputs()]
        self.net_h, self.net_w = resolve_input_size(
            self.input_node.shape, self.custom_input_size
        )

    def _prepare_blob(self, frame):
        orig_h, orig_w = frame.shape[:2]
        if len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif len(frame.shape) == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        padded, r, (pad_x, pad_y) = letterbox(frame, (self.net_h, self.net_w))
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        blob = rgb.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[None, ...]
        return blob, orig_h, orig_w, r, pad_x, pad_y

    def _parse_predictions(self, raw_pred):
        if raw_pred.ndim == 3:
            preds = (
                np.transpose(raw_pred[0], (1, 0))
                if raw_pred.shape[1] < raw_pred.shape[2]
                else raw_pred[0]
            )
        elif raw_pred.ndim == 2:
            preds = raw_pred
        else:
            return None
        if preds.shape[0] == 0 or preds.shape[1] < 5:
            return None
        return preds

    def _filter_candidates(self, preds):
        cx, cy, bw, bh = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
        scores = preds[:, 4:]
        if scores.size > 0 and (scores.min() < 0.0 or scores.max() > 1.0):
            scores = 1.0 / (1.0 + np.exp(-np.clip(scores, -50.0, 50.0)))

        if scores.shape[1] == 1:
            class_ids = np.zeros(len(scores), dtype=int)
            confidences = scores[:, 0]
        else:
            class_ids = np.argmax(scores, axis=1)
            confidences = scores[np.arange(len(scores)), class_ids]

        mask = confidences >= self.conf_threshold
        if self.classes is not None:
            mask = mask & np.isin(class_ids, list(self.classes))
        if not np.any(mask):
            return None
        return cx[mask], cy[mask], bw[mask], bh[mask], class_ids[mask], confidences[mask]

    def _build_detections(self, filtered, r, pad_x, pad_y, orig_w, orig_h):
        cx, cy, bw, bh, class_ids, confidences = filtered
        x1, y1 = cx - bw / 2.0, cy - bh / 2.0
        x2, y2 = cx + bw / 2.0, cy + bh / 2.0

        orig_x1 = np.clip((x1 - pad_x) / r, 0.0, float(orig_w))
        orig_y1 = np.clip((y1 - pad_y) / r, 0.0, float(orig_h))
        orig_x2 = np.clip((x2 - pad_x) / r, 0.0, float(orig_w))
        orig_y2 = np.clip((y2 - pad_y) / r, 0.0, float(orig_h))

        boxes_xyxy = np.column_stack([orig_x1, orig_y1, orig_x2, orig_y2])
        offset = class_ids[:, None].astype(float) * 4096.0
        keep = nms_numpy(boxes_xyxy + offset, confidences, self.iou_threshold)

        results = []
        for idx in keep:
            bx1, by1, bx2, by2 = boxes_xyxy[idx]
            cid = int(class_ids[idx])
            results.append(
                Detection(
                    bbox=(
                        int(round(bx1)),
                        int(round(by1)),
                        max(1, int(round(bx2 - bx1))),
                        max(1, int(round(by2 - by1))),
                    ),
                    class_id=cid,
                    confidence=float(confidences[idx]),
                    label=self.labels.get(cid, f"class_{cid}"),
                )
            )
        return results

    def detect(self, frame):
        """Execute ONNX object detection on input frame."""
        if frame is None or getattr(frame, "size", 0) == 0:
            return []

        blob, orig_h, orig_w, r, pad_x, pad_y = self._prepare_blob(frame)
        outputs = self.session.run(self.output_names, {self.input_name: blob})
        preds = self._parse_predictions(outputs[0])
        if preds is None:
            return []

        filtered = self._filter_candidates(preds)
        if filtered is None:
            return []

        return self._build_detections(filtered, r, pad_x, pad_y, orig_w, orig_h)

    def detect_raw_objects(self, frame, mask=None):
        detections = self.detect(frame)
        return [TailItem(bbox=d.bbox) for d in detections]


# Attach static & class methods for 100% backward compatibility
OnnxDetector.letterbox = staticmethod(letterbox)
OnnxDetector.nms_numpy = staticmethod(nms_numpy)
OnnxDetector.get_available_execution_providers = staticmethod(get_available_execution_providers)


def _create_yolov8_detector(*args, **kwargs):
    if "model_path" not in kwargs and len(args) == 0:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        repo_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
        model_path = os.path.join(repo_root, "models", "yolov8n.onnx")
        if not os.path.isfile(model_path):
            try:
                from intelligent_tracker.detectors.model_loader import ensure_model

                model_path = ensure_model("yolov8n")
            except Exception:
                pass
        kwargs["model_path"] = model_path
    return OnnxDetector(*args, **kwargs)


def _create_yolo11_detector(*args, **kwargs):
    if "model_path" not in kwargs and len(args) == 0:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        repo_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
        model_path = os.path.join(repo_root, "models", "yolo11n.onnx")
        if not os.path.isfile(model_path):
            try:
                from intelligent_tracker.detectors.model_loader import ensure_model

                model_path = ensure_model("yolo11n")
            except Exception:
                pass
        kwargs["model_path"] = model_path
    return OnnxDetector(*args, **kwargs)


Detector.register_detector(OnnxDetector)
DetectorFactory.register("yolov8", _create_yolov8_detector)
DetectorFactory.register("yolov8n", _create_yolov8_detector)
DetectorFactory.register("yolo11", _create_yolo11_detector)
DetectorFactory.register("yolo11n", _create_yolo11_detector)
DetectorFactory.register("onnx", OnnxDetector)
