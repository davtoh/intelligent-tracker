#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Dashboard Domain Services Package.
Provides focused collaborator services for subscriber leasing, frame overlays,
entity tagging, video transcoding, stream workers, and pipeline factories.
"""

from dashboard.services.stream_subscribers import StreamSubscriberRegistry, StreamSubscriberMixin
from dashboard.services.frame_overlay import FrameOverlayRenderer
from dashboard.services.entity_tagger import EntityTaggerService
from dashboard.services.video_transcoder import VideoTranscodeService
from dashboard.services.stream_media import StreamMediaMixin
from dashboard.services.stream_worker import StreamWorker
from dashboard.services.pipeline_factory import StreamPipelineFactory, StreamPipelineBundle, load_stream_config

__all__ = [
    "StreamSubscriberRegistry",
    "StreamSubscriberMixin",
    "FrameOverlayRenderer",
    "EntityTaggerService",
    "VideoTranscodeService",
    "StreamMediaMixin",
    "StreamWorker",
    "StreamPipelineFactory",
    "StreamPipelineBundle",
    "load_stream_config",
]
