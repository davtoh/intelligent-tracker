/**
 * Intelligent Tracker - Video Scrubber Multi-Layer Canvas Detection Overlay.
 *
 * Manages concurrent detection run layers (Map<runId, LayerState>) and
 * progressive live-stream compositing above the HTML5 video element.
 * Geometry math, binary search, and box drawing live in ScrubberOverlayRenderer.
 */

(function () {
  'use strict';

  const FALLBACK_PALETTES = [
    { id: 'cyan', name: 'Cyan', stroke: '#06b6d4', fill: 'rgba(6, 182, 212, 0.16)', labelBg: 'rgba(8, 145, 178, 0.92)', text: '#ffffff' },
    { id: 'amber', name: 'Amber', stroke: '#f59e0b', fill: 'rgba(245, 158, 11, 0.16)', labelBg: 'rgba(180, 83, 9, 0.92)', text: '#ffffff' },
    { id: 'purple', name: 'Purple', stroke: '#a855f7', fill: 'rgba(168, 85, 247, 0.16)', labelBg: 'rgba(126, 34, 206, 0.92)', text: '#ffffff' },
    { id: 'emerald', name: 'Emerald', stroke: '#10b981', fill: 'rgba(16, 185, 129, 0.16)', labelBg: 'rgba(4, 120, 87, 0.92)', text: '#ffffff' },
    { id: 'rose', name: 'Rose', stroke: '#f43f5e', fill: 'rgba(244, 63, 94, 0.16)', labelBg: 'rgba(190, 18, 60, 0.92)', text: '#ffffff' },
  ];

  let videoPlayer = null;
  let overlayCanvas = null;
  let overlayCtx = null;
  const activeLayers = new Map();
  let primaryRunId = null;
  let currentFilename = null;
  let animFrameId = null;
  let progressiveJobId = null;
  let progressiveNextIndex = 0;
  let isFetchingProgressive = false;
  let eventsBound = false;

  function getRenderer() {
    return window.ScrubberOverlayRenderer || null;
  }

  function getPalettes() {
    return getRenderer()?.PALETTES || FALLBACK_PALETTES;
  }

  function getBaseStem(filename) {
    if (!filename) return '';
    return String(filename).trim().replace(/_h264(\.[^.]+)$/i, '$1').replace(/\.[^.]+$/, '');
  }

  function isSameRecording(nameA, nameB) {
    return Boolean(nameA && nameB && getBaseStem(nameA) === getBaseStem(nameB));
  }

  function getPrimaryLayer() {
    if (primaryRunId && activeLayers.has(primaryRunId)) return activeLayers.get(primaryRunId);
    let last = null;
    for (const layer of activeLayers.values()) last = layer;
    return last;
  }

  function init() {
    videoPlayer = document.getElementById('scrubber-video-player');
    overlayCanvas = document.getElementById('scrubber-overlay-canvas');
    if (overlayCanvas) overlayCtx = overlayCanvas.getContext('2d');
    if (!eventsBound) {
      eventsBound = true;
      window.addEventListener('resize', () => render());
      window.addEventListener('video-job-event', handleVideoJobEvent);
    }
  }

  function setLayer(runId, layerState) {
    if (!runId || !layerState) return;
    const key = String(runId);
    activeLayers.set(key, {
      runId: key,
      label: layerState.label || key,
      shortLabel: layerState.shortLabel || '',
      color: layerState.color || getPalettes()[0],
      frameDetections: Array.isArray(layerState.frameDetections) ? layerState.frameDetections : [],
      sourceResolution: Array.isArray(layerState.sourceResolution) ? layerState.sourceResolution : null,
      isLive: Boolean(layerState.isLive),
    });
    primaryRunId = key;
    render();
  }

  function removeLayer(runId) {
    if (!runId) return;
    const key = String(runId);
    if (!activeLayers.delete(key)) return;
    if (primaryRunId === key) {
      const keys = Array.from(activeLayers.keys());
      primaryRunId = keys.length > 0 ? keys[keys.length - 1] : null;
    }
    render();
  }

  function clearLayers(options = {}) {
    if (options.keepLive) {
      for (const [key, layer] of activeLayers.entries()) {
        if (!layer.isLive) activeLayers.delete(key);
      }
    } else {
      activeLayers.clear();
    }
    const keys = Array.from(activeLayers.keys());
    primaryRunId = keys.length > 0 ? keys[keys.length - 1] : null;
    render();
  }

  function removeLiveLayers() {
    for (const [key, layer] of activeLayers.entries()) {
      if (layer.isLive) activeLayers.delete(key);
    }
  }

  async function attachActiveJob(filename, activeJob) {
    progressiveJobId = activeJob.job_id;
    progressiveNextIndex = 0;
    removeLiveLayers();
    if (window.OverlayLayers) await window.OverlayLayers.ensureLoaded(filename);
    await fetchProgressiveStream(activeJob.filename, activeJob.job_id);
  }

  async function loadDetections(filename, runId = null, options = {}) {
    const prevFilename = currentFilename;
    currentFilename = filename;
    if (!filename) {
      progressiveJobId = null;
      progressiveNextIndex = 0;
      clearLayers();
      return;
    }
    if (prevFilename && !isSameRecording(prevFilename, filename)) {
      progressiveJobId = null;
      progressiveNextIndex = 0;
      clearLayers();
    }
    if (!runId && window.VideoJobClient) {
      const activeJob = window.VideoJobClient.getActiveJob(filename);
      if (activeJob && activeJob.job_type === 'analytics') {
        await attachActiveJob(filename, activeJob);
        return;
      }
    }
    if (!runId && window.OverlayLayers) {
      const runs = await window.OverlayLayers.ensureLoaded(filename);
      if (Array.isArray(runs) && runs.length > 0) return;
    }

    progressiveJobId = null;
    progressiveNextIndex = 0;
    try {
      const url = runId
        ? `/api/videos/${encodeURIComponent(filename)}/reports/${encodeURIComponent(runId)}/detections`
        : `/api/videos/${encodeURIComponent(filename)}/detections`;
      const resp = await fetch(url);
      if (!isSameRecording(currentFilename, filename)) return;
      if (!options.additive) clearLayers({ keepLive: true });
      if (resp.ok) {
        const data = await resp.json();
        if (!isSameRecording(currentFilename, filename)) return;
        const layerId = runId || 'default';
        setLayer(layerId, {
          runId: layerId,
          label: options.label || layerId,
          shortLabel: options.shortLabel || '',
          color: options.color || getPalettes()[0],
          frameDetections: data.frame_detections,
          sourceResolution: data.source_resolution,
        });
      }
    } catch (err) {
      console.debug('[ScrubberOverlay] Detection stream unavailable:', err);
      if (!options.additive) clearLayers({ keepLive: true });
    }
  }

  function setDetections(frameDetections, sourceResolution = null, options = {}) {
    progressiveJobId = null;
    progressiveNextIndex = 0;
    if (!options.additive) clearLayers({ keepLive: true });
    const layerId = options.runId || 'default';
    setLayer(layerId, {
      runId: layerId,
      label: options.label || 'Detections',
      shortLabel: options.shortLabel || '',
      color: options.color || getPalettes()[0],
      frameDetections,
      sourceResolution,
    });
  }

  function appendDetections(frameDetections, sourceResolution = null, options = {}) {
    const liveKey = options.layerId || (progressiveJobId ? `live:${progressiveJobId}` : 'live:stream');
    let layer = (!options.reset && activeLayers.get(liveKey)) || null;
    if (!layer) {
      const palette = options.color || window.OverlayLayers?.getNextPalette?.(currentFilename) || getPalettes()[0];
      layer = {
        runId: liveKey,
        label: 'Live Indexing',
        shortLabel: 'LIVE',
        color: palette,
        frameDetections: [],
        sourceResolution: null,
        isLive: true,
      };
      activeLayers.set(liveKey, layer);
    }
    if (Array.isArray(sourceResolution) && sourceResolution.length >= 2) {
      layer.sourceResolution = sourceResolution;
    }
    if (Array.isArray(frameDetections) && frameDetections.length > 0) {
      const prevLast = layer.frameDetections.length > 0 ? layer.frameDetections[layer.frameDetections.length - 1].time : -Infinity;
      const needsSort = frameDetections[0].time < prevLast;
      layer.frameDetections.push(...frameDetections);
      if (needsSort) layer.frameDetections.sort((a, b) => a.time - b.time);
    }
    primaryRunId = liveKey;
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
      if (typeof data.next_index === 'number') progressiveNextIndex = data.next_index;
      appendDetections(data.frame_detections, data.source_resolution, { layerId: `live:${jobId}` });
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
      removeLiveLayers();
      appendDetections([], null, { reset: true, layerId: `live:${job.job_id}` });
    } else if (type === 'job-update' && (job.status === 'running' || job.status === 'pending')) {
      if (progressiveJobId !== job.job_id) {
        progressiveJobId = job.job_id;
        progressiveNextIndex = 0;
        removeLiveLayers();
      }
      fetchProgressiveStream(job.filename, job.job_id);
    } else if (type === 'job-finished') {
      removeLayer(`live:${job.job_id}`);
      if (progressiveJobId === job.job_id) {
        progressiveJobId = null;
        progressiveNextIndex = 0;
      }
      if (job.status === 'completed' && !window.OverlayLayers && job.result?.run_id) {
        loadDetections(currentFilename, job.result.run_id);
      }
    }
  }

  function clear() {
    if (!overlayCanvas || !overlayCtx) return;
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
  }

  function render() {
    const renderer = getRenderer();
    if (!renderer || !overlayCanvas || !overlayCtx || !videoPlayer) return;
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

    if (!videoPlayer.videoWidth || !videoPlayer.videoHeight || vRect.width === 0 || vRect.height === 0 || activeLayers.size === 0) {
      overlayCtx.restore();
      return;
    }

    const { offsetX, offsetY, renderW, renderH } = renderer.computeVideoRenderBox(
      vRect, vpRect, videoPlayer.videoWidth, videoPlayer.videoHeight
    );
    const multiLayer = activeLayers.size > 1;
    const currentTime = videoPlayer.currentTime;

    for (const layer of activeLayers.values()) {
      const record = renderer.findClosestDetections(layer.frameDetections, currentTime);
      if (!record || !record.tracks || record.tracks.length === 0) continue;

      const fallbackRes = layer.sourceResolution || null;
      const { scaleX, scaleY } = renderer.resolveScaleFactors(
        renderW, renderH, record, videoPlayer.videoWidth, videoPlayer.videoHeight, fallbackRes
      );
      const prefix = multiLayer && layer.shortLabel ? `${layer.shortLabel} · ` : '';
      for (let i = 0; i < record.tracks.length; i++) {
        renderer.drawTrackBox(overlayCtx, record.tracks[i], offsetX, offsetY, scaleX, scaleY, layer.color, prefix);
      }
    }

    overlayCtx.restore();
  }

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

  function stopLoop() {
    if (animFrameId) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
    render();
  }

  window.ScrubberOverlay = {
    init,
    loadDetections,
    setDetections,
    appendDetections,
    setLayer,
    removeLayer,
    clearLayers,
    hasLayer: (runId) => activeLayers.has(String(runId)),
    getActiveLayers: () => activeLayers,
    getActiveLayerIds: () => Array.from(activeLayers.keys()),
    fetchProgressiveStream,
    render,
    clear,
    startLoop,
    stopLoop,
    computeVideoRenderBox: (vR, vpR, vw, vh) => getRenderer()?.computeVideoRenderBox(vR, vpR, vw, vh),
    resolveScaleFactors: (rW, rH, rec, vw, vh, fb) =>
      getRenderer()?.resolveScaleFactors(rW, rH, rec, vw, vh, fb ?? getPrimaryLayer()?.sourceResolution ?? null),
    PALETTES: getPalettes(),
    getCurrentDetections: () => getPrimaryLayer()?.frameDetections || [],
    getCurrentRunId: () => getPrimaryLayer()?.runId || null,
    getCurrentSourceResolution: () => getPrimaryLayer()?.sourceResolution || null,
    getProgressiveJobId: () => progressiveJobId,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
