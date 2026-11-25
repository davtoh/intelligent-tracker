/**
 * Unified Enrollment Stage Controller.
 * Manages source context badges, single-stage video+canvas overlay sync,
 * true-FPS frame stepping, and video_filename/media_offset_sec metadata.
 */
(function () {
  'use strict';

  function getActiveVideoFilename() {
    const fromScrubber = window.VideoScrubber?.getCurrentFilename?.()
      || window.VideoScrubber?.getActiveFilename?.();
    if (fromScrubber) return String(fromScrubber);
    const player = document.getElementById('scrubber-video-player');
    if (player?.dataset?.filename) return String(player.dataset.filename);
    const src = player?.getAttribute?.('src') || player?.src || '';
    const match = String(src).match(/\/videos\/([^/?#]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function isVideoStudioActive() {
    const tab = document.getElementById('tab-videos');
    if (tab?.classList?.contains('active')) return true;
    return window.App?.getActiveTab?.() === 'tab-videos';
  }

  function resolvePreferredSource(cams, videos, activeCamId, options = {}) {
    const videoList = Array.isArray(videos) ? videos : [];
    const preferVid = Boolean(options.preferVideo || options.videoFilename || isVideoStudioActive());
    const targetFn = options.videoFilename || getActiveVideoFilename();
    if (preferVid && targetFn && videoList.some((v) => (v.filename || v.name) === targetFn)) {
      return `video:${targetFn}`;
    }
    return activeCamId || '';
  }

  function updateSourceBadge(sourceVal, labelText) {
    const badge = document.getElementById('gallery-enroll-source-badge');
    if (!badge) return;
    if (!sourceVal) {
      badge.textContent = 'Source: Image Upload';
      return;
    }
    if (String(sourceVal).startsWith('video:')) {
      const fn = String(sourceVal).slice(6);
      badge.textContent = `Video: ${fn}`;
      return;
    }
    badge.textContent = `Camera: ${labelText || sourceVal}`;
  }

  function getSelectedSourceMeta(camSelect) {
    const val = camSelect ? (camSelect.value || '') : '';
    const opt = camSelect?.options?.[camSelect.selectedIndex];
    if (val.startsWith('video:')) {
      const vid = document.getElementById('enroll-scrubber-video');
      const fps = Number(opt?.getAttribute?.('data-fps')) || 30;
      const offset = vid && Number.isFinite(Number(vid.currentTime)) ? Number(vid.currentTime) : 0;
      return {
        camera_id: null,
        video_filename: val.slice(6),
        media_offset_sec: Number(offset.toFixed(3)),
        fps,
      };
    }
    return {
      camera_id: val || null,
      video_filename: null,
      media_offset_sec: null,
      fps: 30,
    };
  }

  function syncVideoStageClasses(canvas, isVideo) {
    const vid = document.getElementById('enroll-scrubber-video');
    if (vid) vid.style.display = isVideo ? 'block' : 'none';
    if (canvas?.classList) {
      if (isVideo) canvas.classList.add('is-video-overlay');
      else canvas.classList.remove('is-video-overlay');
    }
  }

  function getActiveVideoCurrentTime() {
    const player = document.getElementById('scrubber-video-player');
    const t = Number(player?.currentTime);
    return Number.isFinite(t) && t > 0 ? t : 0;
  }

  window.EnrollmentStageController = {
    getActiveVideoFilename,
    getActiveVideoCurrentTime,
    isVideoStudioActive,
    resolvePreferredSource,
    updateSourceBadge,
    getSelectedSourceMeta,
    syncVideoStageClasses,
  };
})();
