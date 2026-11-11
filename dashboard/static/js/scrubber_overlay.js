/**
 * Intelligent Tracker - Video Scrubber Canvas Detection Overlay.
 * 
 * Renders real-time bounding boxes, track IDs, labels, and confidence tags
 * on a transparent canvas overlaid directly above the video playback element.
 * 
 * Supports:
 * - Time-indexed frame detection lookup with binary search (O(log N))
 * - High-DPI canvas scaling via window.devicePixelRatio
 * - Responsive aspect-ratio mapping with letterbox/pillarbox offset compensation
 * - Smooth 60fps requestAnimationFrame rendering during active playback
 * - Race-safe async detection loading tied to the active video filename
 */

(function () {
  'use strict';

  let videoPlayer = null;
  let overlayCanvas = null;
  let overlayCtx = null;
  let currentDetections = [];
  let currentFilename = null;
  let currentRunId = null;
  let animFrameId = null;

  function init() {
    videoPlayer = document.getElementById('scrubber-video-player');
    overlayCanvas = document.getElementById('scrubber-overlay-canvas');
    if (overlayCanvas) {
      overlayCtx = overlayCanvas.getContext('2d');
    }
    window.addEventListener('resize', () => {
      render();
    });
  }

  /**
   * Load time-indexed frame detections stream for a video file or specific run.
   */
  async function loadDetections(filename, runId = null) {
    currentFilename = filename;
    currentRunId = runId;
    if (!filename) {
      currentDetections = [];
      clear();
      return;
    }

    try {
      const url = runId
        ? `/api/videos/${encodeURIComponent(filename)}/reports/${encodeURIComponent(runId)}/detections`
        : `/api/videos/${encodeURIComponent(filename)}/detections`;
      const resp = await fetch(url);
      if (resp.ok) {
        const data = await resp.json();
        // Discard if active video changed while network request was in-flight
        if (currentFilename !== filename) return;
        currentDetections = Array.isArray(data.frame_detections) ? data.frame_detections : [];
      } else {
        currentDetections = [];
      }
    } catch (err) {
      console.debug('[ScrubberOverlay] Detection stream unavailable:', err);
      currentDetections = [];
    }
    render();
  }

  /**
   * Set detections stream directly (e.g. from completed batch job payload).
   */
  function setDetections(frameDetections) {
    currentDetections = Array.isArray(frameDetections) ? frameDetections : [];
    render();
  }

  /**
   * Find closest time-indexed detection record using binary search.
   * Allows up to tolerance seconds (default 0.35s) discrepancy for strided analysis.
   */
  function findClosestDetections(currentTime, tolerance = 0.35) {
    if (!currentDetections || currentDetections.length === 0) return null;
    let low = 0;
    let high = currentDetections.length - 1;

    while (low <= high) {
      const mid = (low + high) >> 1;
      const t = currentDetections[mid].time;
      if (t < currentTime) {
        low = mid + 1;
      } else if (t > currentTime) {
        high = mid - 1;
      } else {
        return currentDetections[mid];
      }
    }

    let best = null;
    let bestDiff = Infinity;
    if (low < currentDetections.length) {
      const diff = Math.abs(currentDetections[low].time - currentTime);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = currentDetections[low];
      }
    }
    if (high >= 0) {
      const diff = Math.abs(currentDetections[high].time - currentTime);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = currentDetections[high];
      }
    }
    return bestDiff <= tolerance ? best : null;
  }

  /**
   * Clear the overlay canvas buffer.
   */
  function clear() {
    if (!overlayCanvas || !overlayCtx) return;
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
  }

  /**
   * Render detected bounding boxes for the current video playback timestamp.
   */
  function render() {
    if (!overlayCanvas || !overlayCtx || !videoPlayer) return;
    const viewport = overlayCanvas.parentElement;
    if (!viewport) return;

    const vpRect = viewport.getBoundingClientRect();
    const vRect = videoPlayer.getBoundingClientRect();

    if (vpRect.width === 0 || vpRect.height === 0) return;

    const dpr = window.devicePixelRatio || 1;
    const targetW = Math.round(vpRect.width * dpr);
    const targetH = Math.round(vpRect.height * dpr);

    if (overlayCanvas.width !== targetW || overlayCanvas.height !== targetH) {
      overlayCanvas.width = targetW;
      overlayCanvas.height = targetH;
    }

    overlayCtx.save();
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    overlayCtx.scale(dpr, dpr);

    // Only render if video frame dimensions and element dimensions are valid
    if (!videoPlayer.videoWidth || !videoPlayer.videoHeight || vRect.width === 0 || vRect.height === 0) {
      overlayCtx.restore();
      return;
    }

    // Coordinate mapping: offset of video element inside viewport container
    const left = vRect.left - vpRect.left;
    const top = vRect.top - vpRect.top;
    const scaleX = vRect.width / videoPlayer.videoWidth;
    const scaleY = vRect.height / videoPlayer.videoHeight;

    const record = findClosestDetections(videoPlayer.currentTime);
    if (!record || !record.tracks || record.tracks.length === 0) {
      overlayCtx.restore();
      return;
    }

    for (let i = 0; i < record.tracks.length; i++) {
      const track = record.tracks[i];
      if (!track.bbox || track.bbox.length < 4) continue;
      const [bx, by, bw, bh] = track.bbox;
      const x = left + (bx * scaleX);
      const y = top + (by * scaleY);
      const w = bw * scaleX;
      const h = bh * scaleY;

      const isIdentified = Boolean(track.identity_label);
      const strokeColor = isIdentified ? '#10b981' : '#06b6d4';
      const fillColor = isIdentified ? 'rgba(16, 185, 129, 0.15)' : 'rgba(6, 182, 212, 0.15)';

      // Bounding Box
      overlayCtx.strokeStyle = strokeColor;
      overlayCtx.lineWidth = 2;
      overlayCtx.fillStyle = fillColor;
      overlayCtx.fillRect(x, y, w, h);
      overlayCtx.strokeRect(x, y, w, h);

      // Label Tag
      const conf = track.confidence ? ` ${(track.confidence * 100).toFixed(0)}%` : '';
      const idTag = track.track_id != null ? ` #${track.track_id}` : '';
      const labelText = (track.identity_label || track.label || 'object') + conf + idTag;

      overlayCtx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
      const textMetrics = overlayCtx.measureText(labelText);
      const textHeight = 14;
      const pad = 4;
      const bgWidth = textMetrics.width + (pad * 2);
      const bgHeight = textHeight + pad;
      const labelY = Math.max(top, y - bgHeight);

      overlayCtx.fillStyle = isIdentified ? 'rgba(5, 150, 105, 0.9)' : 'rgba(8, 145, 178, 0.9)';
      overlayCtx.fillRect(x, labelY, bgWidth, bgHeight);

      overlayCtx.fillStyle = '#ffffff';
      overlayCtx.textBaseline = 'top';
      overlayCtx.fillText(labelText, x + pad, labelY + 2);
    }

    overlayCtx.restore();
  }

  /**
   * Start requestAnimationFrame loop during active video playback.
   */
  function startLoop() {
    if (animFrameId) return;
    function loop() {
      render();
      if (videoPlayer && !videoPlayer.paused) {
        animFrameId = requestAnimationFrame(loop);
      } else {
        animFrameId = null;
      }
    }
    animFrameId = requestAnimationFrame(loop);
  }

  /**
   * Stop requestAnimationFrame loop when video is paused or ended.
   */
  function stopLoop() {
    if (animFrameId) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
    render();
  }

  window.ScrubberOverlay = {
    init: init,
    loadDetections: loadDetections,
    setDetections: setDetections,
    render: render,
    clear: clear,
    startLoop: startLoop,
    stopLoop: stopLoop,
    getCurrentDetections: () => currentDetections,
    getCurrentRunId: () => currentRunId,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

