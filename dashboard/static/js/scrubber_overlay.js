/**
 * Intelligent Tracker - Video Scrubber Multi-Layer Canvas Detection Overlay.
 *
 * Manages concurrent detection run layers (Map<runId, LayerState>) and
 * progressive live-stream compositing above the HTML5 video element.
 * Geometry math, binary search, and box drawing live in ScrubberOverlayRenderer.
 */

(function () {
  'use strict';

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
  const featureVisibility = {
    ...(window.UnifiedCanvasOverlay?.DEFAULT_VISIBILITY || {
      bboxes: true, track_ids: true, dwell_timers: true,
      velocity: false, zones: true, tripwires: true, heatmap: false,
    }),
  };

  function getRenderer() { return window.ScrubberOverlayRenderer || null; }
  function getPalettes() { return window.UnifiedCanvasOverlay?.PALETTES || getRenderer()?.PALETTES || []; }
  function setFeatureVisibility(key, enabled) {
    if (!key || !(key in featureVisibility)) return;
    featureVisibility[key] = Boolean(enabled);
    render();
  }
  function getFeatureVisibility() { return { ...featureVisibility }; }

  function getBaseStem(filename) {
    return filename ? String(filename).trim().replace(/_h264(\.[^.]+)$/i, '$1').replace(/\.[^.]+$/, '') : '';
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

  function getTracksAtCurrentTime() {
    if (!videoPlayer) return [];
    const renderer = getRenderer(), t = videoPlayer.currentTime || 0, out = [];
    for (const layer of activeLayers.values()) {
      const rec = renderer?.findClosestDetections(layer.frameDetections, t);
      const srcRes = rec?.source_resolution || layer.sourceResolution || null;
      if (Array.isArray(rec?.tracks)) rec.tracks.forEach((trk) => out.push({ ...trk, _layerId: layer.runId, _sourceRes: srcRes }));
    }
    return out;
  }

  function bindRoiTagger() {
    if (!overlayCanvas || !window.RoiDrawTagger?.attach) return;
    overlayCanvas.style.pointerEvents = 'auto';
    overlayCanvas.style.cursor = 'crosshair';
    window.RoiDrawTagger.attach({
      canvas: overlayCanvas, mediaEl: videoPlayer, containerEl: overlayCanvas.parentElement,
      getTracks: getTracksAtCurrentTime,
      getSourceContext: () => {
        const res = getPrimaryLayer()?.sourceResolution || null;
        return {
          sourceType: 'video', videoFilename: currentFilename || '',
          timestampSec: videoPlayer?.currentTime || 0,
          sourceWidth: (Array.isArray(res) && res[0] > 0) ? res[0] : (videoPlayer?.videoWidth || 0),
          sourceHeight: (Array.isArray(res) && res[1] > 0) ? res[1] : (videoPlayer?.videoHeight || 0),
        };
      },
      onRenderOverlay: () => render(true),
      onTrackClick: ({ track, overlappingTracks, sourceContext }) => window.RoiDrawTagger.openWithRecognition({ ...sourceContext, track, overlappingTracks, bbox: track.bbox }),
      onRoiDrawn: ({ bbox, sourceContext }) => window.RoiDrawTagger.openWithRecognition({ ...sourceContext, track: null, bbox }),
    });
  }

  let lastRenderKey = '';
  function init() {
    videoPlayer = document.getElementById('scrubber-video-player');
    overlayCanvas = document.getElementById('scrubber-overlay-canvas');
    if (overlayCanvas) overlayCtx = overlayCanvas.getContext('2d');
    bindRoiTagger();
    if (!eventsBound) {
      eventsBound = true;
      window.addEventListener('resize', () => render(true));
      window.addEventListener('video-job-event', handleVideoJobEvent);
      if (window.ResizeObserver && overlayCanvas?.parentElement) {
        new ResizeObserver(() => render(true)).observe(overlayCanvas.parentElement);
      }
    }
  }

  function setLayer(runId, layerState) {
    if (!runId || !layerState) return;
    const key = String(runId);
    activeLayers.set(key, {
      runId: key, label: layerState.label || key, shortLabel: layerState.shortLabel || '',
      color: layerState.color || getPalettes()[0],
      frameDetections: Array.isArray(layerState.frameDetections) ? layerState.frameDetections : [],
      sourceResolution: Array.isArray(layerState.sourceResolution) ? layerState.sourceResolution : null,
      isLive: Boolean(layerState.isLive),
    });
    primaryRunId = key;
    render();
  }

  function removeLayer(runId) {
    if (!runId || !activeLayers.delete(String(runId))) return;
    if (primaryRunId === String(runId)) {
      const keys = Array.from(activeLayers.keys());
      primaryRunId = keys.length > 0 ? keys[keys.length - 1] : null;
    }
    render();
  }

  function clearLayers(options = {}) {
    if (options.keepLive) {
      for (const [key, layer] of activeLayers.entries()) if (!layer.isLive) activeLayers.delete(key);
    } else {
      activeLayers.clear();
    }
    const keys = Array.from(activeLayers.keys());
    primaryRunId = keys.length > 0 ? keys[keys.length - 1] : null;
    render();
  }

  function removeLiveLayers() {
    for (const [key, layer] of activeLayers.entries()) if (layer.isLive) activeLayers.delete(key);
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
    if (!filename) { progressiveJobId = null; progressiveNextIndex = 0; clearLayers(); return; }
    if (prevFilename && !isSameRecording(prevFilename, filename)) { progressiveJobId = null; progressiveNextIndex = 0; clearLayers(); }
    if (!runId && window.VideoJobClient) {
      const activeJob = window.VideoJobClient.getActiveJob(filename);
      if (activeJob && activeJob.job_type === 'analytics') { await attachActiveJob(filename, activeJob); return; }
    }
    if (!runId && window.OverlayLayers) {
      const runs = await window.OverlayLayers.ensureLoaded(filename);
      if (Array.isArray(runs) && runs.length > 0) return;
    }
    progressiveJobId = null;
    progressiveNextIndex = 0;
    try {
      const url = runId ? `/api/videos/${encodeURIComponent(filename)}/reports/${encodeURIComponent(runId)}/detections` : `/api/videos/${encodeURIComponent(filename)}/detections`;
      const resp = await fetch(url);
      if (!isSameRecording(currentFilename, filename)) return;
      if (!options.additive) clearLayers({ keepLive: true });
      if (resp.ok) {
        const data = await resp.json();
        if (!isSameRecording(currentFilename, filename)) return;
        const layerId = runId || 'default';
        setLayer(layerId, { runId: layerId, label: options.label || layerId, shortLabel: options.shortLabel || '', color: options.color || getPalettes()[0], frameDetections: data.frame_detections, sourceResolution: data.source_resolution });
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
    setLayer(layerId, { runId: layerId, label: options.label || 'Detections', shortLabel: options.shortLabel || '', color: options.color || getPalettes()[0], frameDetections, sourceResolution });
  }

  function appendDetections(frameDetections, sourceResolution = null, options = {}) {
    const liveKey = options.layerId || (progressiveJobId ? `live:${progressiveJobId}` : 'live:stream');
    let layer = (!options.reset && activeLayers.get(liveKey)) || null;
    if (!layer) {
      const palette = options.color || window.OverlayLayers?.getNextPalette?.(currentFilename) || getPalettes()[0];
      layer = { runId: liveKey, label: 'Live Indexing', shortLabel: 'LIVE', color: palette, frameDetections: [], sourceResolution: null, isLive: true };
      activeLayers.set(liveKey, layer);
    }
    if (Array.isArray(sourceResolution) && sourceResolution.length >= 2) layer.sourceResolution = sourceResolution;
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

  function syncViewportCanvas(vpRect) {
    const u = window.UnifiedCanvasOverlay;
    if (u?.syncCanvasDpr) {
      u.syncCanvasDpr(overlayCanvas, overlayCtx, vpRect.width, vpRect.height, undefined, { responsive: true });
      overlayCtx.clearRect(0, 0, vpRect.width, vpRect.height);
      return;
    }
    const dpr = window.devicePixelRatio || 1;
    const targetW = Math.round(vpRect.width * dpr), targetH = Math.round(vpRect.height * dpr);
    if (overlayCanvas.width !== targetW || overlayCanvas.height !== targetH) { overlayCanvas.width = targetW; overlayCanvas.height = targetH; }
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    overlayCtx.scale(dpr, dpr);
  }

  function render(force = false) {
    const renderer = getRenderer();
    if (!renderer || !overlayCanvas || !overlayCtx || !videoPlayer) return;
    const viewport = overlayCanvas.parentElement;
    if (!viewport) return;
    const vpRect = viewport.getBoundingClientRect();
    const vRect = videoPlayer.getBoundingClientRect();
    if (vpRect.width === 0 || vpRect.height === 0) return;
    const currentTime = videoPlayer.currentTime || 0;
    const renderKey = `${activeLayers.size}|${currentTime}|${Math.round(vpRect.width)}x${Math.round(vpRect.height)}`;
    if (!force && activeLayers.size === 0 && renderKey === lastRenderKey) return;
    lastRenderKey = renderKey;
    overlayCtx.save();
    syncViewportCanvas(vpRect);
    if (!videoPlayer.videoWidth || !videoPlayer.videoHeight || vRect.width === 0 || vRect.height === 0 || activeLayers.size === 0) {
      overlayCtx.restore();
      return;
    }
    const { offsetX, offsetY, renderW, renderH } = renderer.computeVideoRenderBox(vRect, vpRect, videoPlayer.videoWidth, videoPlayer.videoHeight);
    const multiLayer = activeLayers.size > 1;
    for (const layer of activeLayers.values()) {
      const record = renderer.findClosestDetections(layer.frameDetections, currentTime);
      if (!record || ((!record.tracks || record.tracks.length === 0) && !record.zones && !record.tripwires && !record.heatmap)) continue;
      const { scaleX, scaleY } = renderer.resolveScaleFactors(renderW, renderH, record, videoPlayer.videoWidth, videoPlayer.videoHeight, layer.sourceResolution || null);
      const prefix = multiLayer && layer.shortLabel ? `${layer.shortLabel} · ` : '';
      renderer.renderLayerRecord(overlayCtx, record, { offsetX, offsetY, scaleX, scaleY, renderW, renderH }, layer.color, prefix, featureVisibility);
    }
    overlayCtx.restore();
  }

  function startLoop() {
    if (animFrameId) return;
    function loop() {
      if (activeLayers.size > 0 || lastRenderKey === '') render();
      animFrameId = (videoPlayer && !videoPlayer.paused) ? requestAnimationFrame(loop) : null;
    }
    animFrameId = requestAnimationFrame(loop);
  }

  function stopLoop() {
    if (animFrameId) { cancelAnimationFrame(animFrameId); animFrameId = null; }
    render(true);
  }

  window.ScrubberOverlay = {
    init, loadDetections, setDetections, appendDetections, setLayer, removeLayer, clearLayers,
    hasLayer: (runId) => activeLayers.has(String(runId)),
    getActiveLayers: () => activeLayers,
    getActiveLayerIds: () => Array.from(activeLayers.keys()),
    fetchProgressiveStream, render, clear, startLoop, stopLoop, setFeatureVisibility, getFeatureVisibility,
    computeVideoRenderBox: (vR, vpR, vw, vh) => getRenderer()?.computeVideoRenderBox(vR, vpR, vw, vh),
    resolveScaleFactors: (rW, rH, rec, vw, vh, fb) => getRenderer()?.resolveScaleFactors(rW, rH, rec, vw, vh, fb ?? getPrimaryLayer()?.sourceResolution ?? null),
    get PALETTES() { return getPalettes(); },
    getCurrentDetections: () => getPrimaryLayer()?.frameDetections || [],
    getCurrentRunId: () => getPrimaryLayer()?.runId || null,
    getCurrentSourceResolution: () => getPrimaryLayer()?.sourceResolution || null,
    getProgressiveJobId: () => progressiveJobId,
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
