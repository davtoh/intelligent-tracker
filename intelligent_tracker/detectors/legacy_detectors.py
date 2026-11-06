"""Legacy detector class stubs for backwards compatibility."""

from intelligent_tracker.detectors.core_detector import Detector


class PeopleDetector(Detector):
    pass


class ObjectDetector(Detector):
    pass


class MovementDetector(Detector):
    pass


Detector.register_detector(PeopleDetector)
Detector.register_detector(ObjectDetector)
Detector.register_detector(MovementDetector)

