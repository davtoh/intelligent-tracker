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
  let currentSourceResolution = null;
  let animFrameId = null;
  let progressiveJobId = null;
  let progressiveNextIndex = 0;
  let isFetchingProgressive = false;
  let eventsBound = false;

  function getBaseStem(filename) {
    if (!filename) return '';
    return String(filename).trim().replace(/_h264(\.[^.]+)$/i, '$1').replace(/\.[^.]+$/, '');
  }

  function isSameRecording(nameA, nameB) {
    return Boolean(nameA && nameB && getBaseStem(nameA) === getBaseStem(nameB));
  }

  function init() {
    videoPlayer = document.getElementById('scrubber-video-player');
    overlayCanvas = document.getElementById('scrubber-overlay-canvas');
    if (overlayCanvas) {
      overlayCtx = overlayCanvas.getContext('2d');
    }
    if (!eventsBound) {
      eventsBound = true;
      window.addEventListener('resize', () => render());
      window.addEventListener('video-job-event', handleVideoJobEvent);
    }
  }

  /**
   * Load time-indexed frame detections stream for a video file or specific run.
   */
  async function loadDetections(filename, runId = null) {
    currentFilename = filename;
    currentRunId = runId;
    if (!filename) {
      progressiveJobId = null;
      progressiveNextIndex = 0;
      currentDetections = [];
      currentSourceResolution = null;
      clear();
      return;
    }

    if (!runId && window.VideoJobClient) {
      const activeJob = window.VideoJobClient.getActiveJob(filename);
      if (activeJob && activeJob.job_type === 'analytics') {
        progressiveJobId = activeJob.job_id;
        progressiveNextIndex = 0;
        currentDetections = [];
        await fetchProgressiveStream(activeJob.filename, activeJob.job_id);
        return;
      }
    }

    progressiveJobId = null;
    progressiveNextIndex = 0;
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
        currentSourceResolution = Array.isArray(data.source_resolution) ? data.source_resolution : null;
      } else {
        currentDetections = [];
        currentSourceResolution = null;
      }
    } catch (err) {
      console.debug('[ScrubberOverlay] Detection stream unavailable:', err);
      currentDetections = [];
      currentSourceResolution = null;
    }
    render();
  }

  /**
   * Set detections stream directly (e.g. from completed batch job payload).
   */
  function setDetections(frameDetections, sourceResolution = null) {
    progressiveJobId = null;
    progressiveNextIndex = 0;
    currentDetections = Array.isArray(frameDetections) ? frameDetections : [];
    currentSourceResolution = Array.isArray(sourceResolution) ? sourceResolution : null;
    render();
  }

  /**
   * Append progressive frame detections from an active analytics job and redraw.
   */
  function appendDetections(frameDetections, sourceResolution = null, options = {}) {
    if (options.reset) currentDetections = [];
    if (Array.isArray(sourceResolution) && sourceResolution.length >= 2) {
      currentSourceResolution = sourceResolution;
    }
    if (Array.isArray(frameDetections) && frameDetections.length > 0) {
      const prevLast = currentDetections.length > 0 ? currentDetections[currentDetections.length - 1].time : -Infinity;
      const needsSort = frameDetections[0].time < prevLast;
      currentDetections.push(...frameDetections);
      if (needsSort) currentDetections.sort((a, b) => a.time - b.time);
    }
    render();
  }

  async function fetchProgressiveStream(filename, jobId) {
    if (!filename || !jobId || isFetchingProgressive || !isSameRecording(currentFilename, filename)) return;
    isFetchingProgressive = true;
    try {
      const url = `/api/videos/${encodeURIComponent(filename)}/jobs/${encodeURIComponent(jobId)}/stream?since=${progressiveNextIndex}`;
      const resp = await fetch(url);
      if (!resp.ok) return;
      const data = await resp.json();
      if (!isSameRecording(currentFilename, filename)) return;
      if (progressiveJobId && progressiveJobId !== jobId) return;
      if (typeof data.next_index === 'number') {
        progressiveNextIndex = data.next_index;
      }
      appendDetections(data.frame_detections, data.source_resolution);
    } catch (err) {
      console.debug('[ScrubberOverlay] Progressive stream poll error:', err);
    } finally {
      isFetchingProgressive = false;
    }
  }

  function handleVideoJobEvent(e) {
    const { type, data: job } = e.detail || {};
    if (!job || job.job_type !== 'analytics' || !isSameRecording(currentFilename, job.filename)) return;
    if (type === 'job-started') {
      progressiveJobId = job.job_id;
      progressiveNextIndex = 0;
      currentRunId = null;
      currentDetections = [];
      clear();
    } else if (type === 'job-update') {
      if (job.status === 'running' || job.status === 'pending') {
        if (progressiveJobId !== job.job_id) {
          progressiveJobId = job.job_id;
          progressiveNextIndex = 0;
          currentRunId = null;
          currentDetections = [];
        }
        fetchProgressiveStream(job.filename, job.job_id);
      }
    } else if (type === 'job-finished') {
      if (progressiveJobId === job.job_id) {
        progressiveJobId = null;
        progressiveNextIndex = 0;
      }
      if (job.status === 'completed' && currentFilename !== job.filename && job.result?.run_id) {
        loadDetections(currentFilename, job.result.run_id);
      }
    }
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
   * Compute rendered video rectangle inside object-fit: contain element box,
   * accounting for letterbox (top/bottom) or pillarbox (left/right) offsets.
   */
  function computeVideoRenderBox(vRect, vpRect, videoWidth, videoHeight) {
    const videoAspect = videoWidth / videoHeight;
    const elemAspect = vRect.width / vRect.height;
    let renderW, renderH, renderLeft, renderTop;

    if (elemAspect > videoAspect) {
      // Pillarboxed: black bars on left & right
      renderH = vRect.height;
      renderW = renderH * videoAspect;
      renderLeft = (vRect.width - renderW) / 2;
      renderTop = 0;
    } else {
      // Letterboxed: black bars on top & bottom
      renderW = vRect.width;
      renderH = renderW / videoAspect;
      renderLeft = 0;
      renderTop = (vRect.height - renderH) / 2;
    }

    return {
      offsetX: (vRect.left - vpRect.left) + renderLeft,
      offsetY: (vRect.top - vpRect.top) + renderTop,
      renderW: renderW,
      renderH: renderH,
      scale: renderW / videoWidth,
    };
  }

  /**
   * Compute horizontal and vertical scale factors from source detection resolution
   * to the rendered video viewport box, preserving alignment across transcoded resolutions.
   */
  function resolveScaleFactors(renderW, renderH, record, videoWidth, videoHeight) {
    const srcRes = (Array.isArray(record?.source_resolution) && record.source_resolution.length >= 2)
      ? record.source_resolution
      : (Array.isArray(currentSourceResolution) && currentSourceResolution.length >= 2
          ? currentSourceResolution
          : [videoWidth, videoHeight]);
    const srcW = Number(srcRes[0]) > 0 ? Number(srcRes[0]) : videoWidth;
    const srcH = Number(srcRes[1]) > 0 ? Number(srcRes[1]) : videoHeight;
    return {
      scaleX: renderW / srcW,
      scaleY: renderH / srcH,
    };
  }

  /**
   * Draw a single tracked bounding box and clamped label onto the overlay canvas.
   */
  function drawTrackBox(track, offsetX, offsetY, scaleX, scaleY) {
    if (!track.bbox || track.bbox.length < 4) return;
    const [bx, by, bw, bh] = track.bbox;
    const x = offsetX + (bx * scaleX);
    const y = offsetY + (by * scaleY);
    const w = bw * scaleX;
    const h = bh * scaleY;

    const isIdentified = Boolean(track.identity_label);
    const strokeColor = isIdentified ? '#10b981' : '#06b6d4';
    const fillColor = isIdentified ? 'rgba(16, 185, 129, 0.15)' : 'rgba(6, 182, 212, 0.15)';

    overlayCtx.strokeStyle = strokeColor;
    overlayCtx.lineWidth = 2;
    overlayCtx.fillStyle = fillColor;
    overlayCtx.fillRect(x, y, w, h);
    overlayCtx.strokeRect(x, y, w, h);

    const conf = track.confidence ? ` ${(track.confidence * 100).toFixed(0)}%` : '';
    const idTag = track.track_id != null ? ` #${track.track_id}` : '';
    const labelText = (track.identity_label || track.label || 'object') + conf + idTag;

    overlayCtx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    const textMetrics = overlayCtx.measureText(labelText);
    const textHeight = 14;
    const pad = 4;
    const bgWidth = textMetrics.width + (pad * 2);
    const bgHeight = textHeight + pad;
    const labelY = Math.max(offsetY, y - bgHeight);

    overlayCtx.fillStyle = isIdentified ? 'rgba(5, 150, 105, 0.9)' : 'rgba(8, 145, 178, 0.9)';
    overlayCtx.fillRect(x, labelY, bgWidth, bgHeight);

    overlayCtx.fillStyle = '#ffffff';
    overlayCtx.textBaseline = 'top';
    overlayCtx.fillText(labelText, x + pad, labelY + 2);
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

    if (!videoPlayer.videoWidth || !videoPlayer.videoHeight || vRect.width === 0 || vRect.height === 0) {
      overlayCtx.restore();
      return;
    }

    const { offsetX, offsetY, renderW, renderH } = computeVideoRenderBox(
      vRect, vpRect, videoPlayer.videoWidth, videoPlayer.videoHeight
    );
    const record = findClosestDetections(videoPlayer.currentTime);
    if (!record || !record.tracks || record.tracks.length === 0) {
      overlayCtx.restore();
      return;
    }

    const { scaleX, scaleY } = resolveScaleFactors(
      renderW, renderH, record, videoPlayer.videoWidth, videoPlayer.videoHeight
    );
    for (let i = 0; i < record.tracks.length; i++) {
      drawTrackBox(record.tracks[i], offsetX, offsetY, scaleX, scaleY);
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
    appendDetections: appendDetections,
    fetchProgressiveStream: fetchProgressiveStream,
    render: render,
    clear: clear,
    startLoop: startLoop,
    stopLoop: stopLoop,
    computeVideoRenderBox: computeVideoRenderBox,
    resolveScaleFactors: resolveScaleFactors,
    getCurrentDetections: () => currentDetections,
    getCurrentRunId: () => currentRunId,
    getCurrentSourceResolution: () => currentSourceResolution,
    getProgressiveJobId: () => progressiveJobId,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

