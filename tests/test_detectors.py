#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Edge AI Detector Architecture (Milestone 2).

Tests:
- BaseDetector abstract interface and Detection namedtuple contract
- MockDetector deterministic generation and raw object bridging
- DetectorFactory registration, lookup, case-insensitivity, and error handling
- HaarCascadeDetector, FaceDetector, and EyeDetector concrete implementations
- ColorDetector BaseDetector interface integration
- OnnxDetector execution provider cascade, letterbox preprocessor, pure NumPy NMS,
  and end-to-end inference with YOLOv8n and YOLO11n models
"""

import os
import unittest
import numpy as np
import cv2

from intelligent_tracker.detectors import (
    Detection,
    BaseDetector,
    Detector,
    DetectorFactory,
    HaarCascadeDetector,
    FaceDetector,
    EyeDetector,
    ColorDetector,
    MockDetector,
    OnnxDetector,
    COCO_CLASSES,
)
from intelligent_tracker.core import TailItem


class TestBaseDetectorInterface(unittest.TestCase):
    """Verify BaseDetector contract and Detection data structure."""

    def test_detection_namedtuple_fields(self):
        d = Detection(bbox=(10, 20, 30, 40), class_id=0, confidence=0.85, label="person")
        self.assertEqual(d.bbox, (10, 20, 30, 40))
        self.assertEqual(d.class_id, 0)
        self.assertEqual(d.confidence, 0.85)
        self.assertEqual(d.label, "person")
        self.assertEqual(d[0], (10, 20, 30, 40))
        self.assertEqual(d[1], 0)
        self.assertEqual(d[2], 0.85)
        self.assertEqual(d[3], "person")

    def test_cannot_instantiate_abstract_base_detector(self):
        with self.assertRaises(TypeError):
            BaseDetector()

    def test_concrete_subclass_implements_detect(self):
        class DummyDetector(BaseDetector):
            def detect(self, frame):
                return [Detection(bbox=(0, 0, 10, 10), class_id=0, confidence=1.0, label="dummy")]

        inst = DummyDetector()
        res = inst.detect(np.zeros((100, 100, 3), dtype=np.uint8))
        self.assertEqual(len(res), 1)
        self.assertIsInstance(res[0], Detection)


class TestMockDetector(unittest.TestCase):
    """Verify MockDetector for CI/headless simulation."""

    def test_mock_detector_default_generation(self):
        mock = MockDetector(width=640, height=480, step=10)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        dets1 = mock.detect(frame)
        self.assertEqual(len(dets1), 1)
        d1 = dets1[0]
        self.assertIsInstance(d1, Detection)
        self.assertEqual(d1.class_id, 0)
        self.assertEqual(d1.label, "mock_person")
        self.assertEqual(d1.confidence, 0.95)

        # Subsequent call advances the moving box
        dets2 = mock.detect(frame)
        self.assertEqual(len(dets2), 1)
        d2 = dets2[0]
        self.assertNotEqual(d1.bbox, d2.bbox)

    def test_mock_detector_preset_boxes(self):
        preset = [(15, 25, 40, 80), (100, 120, 50, 90)]
        mock = MockDetector(boxes=preset)
        dets = mock.detect()
        self.assertEqual(len(dets), 2)
        self.assertEqual(dets[0].bbox, (15, 25, 40, 80))
        self.assertEqual(dets[1].bbox, (100, 120, 50, 90))

    def test_mock_detector_detect_raw_objects(self):
        mock = MockDetector(boxes=[(20, 30, 50, 60)])
        raw = mock.detect_raw_objects(np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertIsNotNone(raw)
        self.assertEqual(len(raw), 1)
        self.assertIsInstance(raw[0], TailItem)
        self.assertEqual(raw[0].bbox, (20, 30, 50, 60))


class TestDetectorFactory(unittest.TestCase):
    """Verify registry, creation, and aliases in DetectorFactory."""

    def test_available_detectors(self):
        avail = DetectorFactory.available()
        self.assertIn("mock", avail)
        self.assertIn("haar", avail)
        self.assertIn("face", avail)
        self.assertIn("eye", avail)
        self.assertIn("color", avail)
        self.assertIn("yolov8", avail)
        self.assertIn("yolo11", avail)

    def test_create_mock(self):
        mock = DetectorFactory.create("mock")
        self.assertIsInstance(mock, MockDetector)

    def test_create_case_insensitive(self):
        mock = DetectorFactory.create("MOCK")
        self.assertIsInstance(mock, MockDetector)
        haar = DetectorFactory.create("HaAr")
        self.assertIsInstance(haar, HaarCascadeDetector)

    def test_create_haar(self):
        haar = DetectorFactory.create("haar")
        self.assertIsInstance(haar, HaarCascadeDetector)

    def test_create_face(self):
        face = DetectorFactory.create("face")
        self.assertIsInstance(face, FaceDetector)

    def test_create_eye(self):
        eye = DetectorFactory.create("eye")
        self.assertIsInstance(eye, EyeDetector)

    def test_create_color(self):
        color = DetectorFactory.create("color", [0, 100, 100], [10, 255, 255])
        self.assertIsInstance(color, ColorDetector)

    def test_unregistered_name_raises_key_error(self):
        with self.assertRaises(KeyError):
            DetectorFactory.create("non_existent_detector_name_123")

    def test_custom_registration(self):
        class CustomDetector(Detector):
            def detect(self, frame):
                return []

        DetectorFactory.register("custom_test_det", CustomDetector)
        self.assertIn("custom_test_det", DetectorFactory.available())
        inst = DetectorFactory.create("custom_test_det")
        self.assertIsInstance(inst, CustomDetector)


class TestHaarCascadeDetector(unittest.TestCase):
    """Verify HaarCascadeDetector and concrete subclasses."""

    def test_instantiation_and_empty_frame(self):
        det = HaarCascadeDetector()
        self.assertIsInstance(det, Detector)
        self.assertIsInstance(det, BaseDetector)
        # Empty / black image returns no detections without crashing
        res = det.detect(np.zeros((300, 300, 3), dtype=np.uint8))
        self.assertEqual(res, [])

    def test_subclasses_hierarchy(self):
        self.assertTrue(issubclass(FaceDetector, HaarCascadeDetector))
        self.assertTrue(issubclass(EyeDetector, HaarCascadeDetector))
        self.assertTrue(issubclass(FaceDetector, BaseDetector))
        self.assertTrue(issubclass(EyeDetector, BaseDetector))


class TestColorDetector(unittest.TestCase):
    """Verify ColorDetector BaseDetector interface."""

    def test_color_detector_detect(self):
        det = ColorDetector([0, 100, 100], [10, 255, 255])
        self.assertIsInstance(det, BaseDetector)
        # Blank black frame
        res = det.detect(np.zeros((200, 200, 3), dtype=np.uint8))
        self.assertEqual(res, [])

        # Frame with a red square (HSV: H near 0, high S, high V)
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        # Red in BGR is (0, 0, 255)
        cv2.rectangle(frame, (50, 50), (100, 100), (0, 0, 255), -1)
        res2 = det.detect(frame)
        self.assertGreater(len(res2), 0)
        self.assertIsInstance(res2[0], Detection)
        bx, by, bw, bh = res2[0].bbox
        self.assertAlmostEqual(bx, 50, delta=10)
        self.assertAlmostEqual(by, 50, delta=10)


class TestOnnxDetector(unittest.TestCase):
    """Verify OnnxDetector preprocessing, NMS, execution providers, and inference."""

    def test_execution_providers_priority(self):
        providers = OnnxDetector.get_available_execution_providers()
        self.assertIsInstance(providers, list)
        self.assertIn("CPUExecutionProvider", providers)
        # Custom requested providers
        custom = OnnxDetector.get_available_execution_providers(["CPUExecutionProvider"])
        self.assertEqual(custom, ["CPUExecutionProvider"])

    def test_letterbox_preprocessing(self):
        # 400x200 image letterboxed to 640x640
        frame = np.zeros((200, 400, 3), dtype=np.uint8)
        padded, r, (pad_x, pad_y) = OnnxDetector.letterbox(frame, target_shape=(640, 640))
        self.assertEqual(padded.shape, (640, 640, 3))
        # r = min(640/400, 640/200) = 1.6
        self.assertAlmostEqual(r, 1.6, places=2)
        # new_w = 640, pad_x = 0
        self.assertEqual(pad_x, 0.0)
        # new_h = 320, pad_y = (640-320)/2 = 160
        self.assertEqual(pad_y, 160.0)

    def test_nms_numpy(self):
        # Two overlapping boxes and one separate box
        boxes = np.array([
            [10.0, 10.0, 50.0, 50.0],
            [12.0, 12.0, 48.0, 48.0],
            [200.0, 200.0, 250.0, 250.0],
        ])
        scores = np.array([0.90, 0.85, 0.95])
        kept = OnnxDetector.nms_numpy(boxes, scores, iou_threshold=0.5)
        # Box 2 (score 0.95) kept, Box 0 (score 0.90) kept, Box 1 (IoU high with 0) suppressed
        self.assertIn(2, kept)
        self.assertIn(0, kept)
        self.assertNotIn(1, kept)

    def test_nms_numpy_edge_cases(self):
        # Empty input
        self.assertEqual(OnnxDetector.nms_numpy(np.empty((0, 4)), np.empty(0)), [])
        # Single box
        single = OnnxDetector.nms_numpy(np.array([[0, 0, 10, 10]]), np.array([0.9]))
        self.assertEqual(single, [0])

    def test_yolov8n_inference(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        model_path = os.path.join(repo_root, "models", "yolov8n.onnx")
        if not os.path.isfile(model_path):
            self.skipTest("yolov8n.onnx not present in models/")

        detector = OnnxDetector(model_path=model_path, conf_threshold=0.25)
        self.assertEqual(detector.active_provider, "CPUExecutionProvider")
        self.assertEqual((detector.net_h, detector.net_w), (640, 640))

        # Blank black frame should yield 0 detections
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        dets = detector.detect(frame)
        self.assertEqual(dets, [])

        # Frame bounds validation
        # Feed synthetic image and verify that any detections fall within [0, W] and [0, H]
        test_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        test_dets = detector.detect(test_frame)
        for d in test_dets:
            x, y, w, h = d.bbox
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, 640)
            self.assertLessEqual(y + h, 480)
            self.assertGreaterEqual(d.confidence, 0.25)
            self.assertLessEqual(d.confidence, 1.0)
            self.assertIn(d.label, COCO_CLASSES)

    def test_yolo11n_inference(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        model_path = os.path.join(repo_root, "models", "yolo11n.onnx")
        if not os.path.isfile(model_path):
            self.skipTest("yolo11n.onnx not present in models/")

        detector = OnnxDetector(model_path=model_path, conf_threshold=0.25)
        self.assertEqual(detector.active_provider, "CPUExecutionProvider")

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        dets = detector.detect(frame)
        self.assertEqual(dets, [])

    def test_class_filtering(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        model_path = os.path.join(repo_root, "models", "yolov8n.onnx")
        if not os.path.isfile(model_path):
            self.skipTest("yolov8n.onnx not present in models/")

        # Filter for person only by name and by ID
        det_name = OnnxDetector(model_path=model_path, classes=["person"])
        self.assertEqual(det_name.classes, {0})

        det_id = OnnxDetector(model_path=model_path, classes=[0, 2])
        self.assertEqual(det_id.classes, {0, 2})


if __name__ == "__main__":
    unittest.main()
