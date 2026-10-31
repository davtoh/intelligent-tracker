#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Dashboard Domain Services Package.
Provides focused collaborator services for subscriber leasing, frame overlays,
entity tagging, and video transcoding.
"""

from dashboard.services.stream_subscribers import StreamSubscriberRegistry
from dashboard.services.frame_overlay import FrameOverlayRenderer
from dashboard.services.entity_tagger import EntityTaggerService
from dashboard.services.video_transcoder import VideoTranscodeService

__all__ = [
    "StreamSubscriberRegistry",
    "FrameOverlayRenderer",
    "EntityTaggerService",
    "VideoTranscodeService",
]

