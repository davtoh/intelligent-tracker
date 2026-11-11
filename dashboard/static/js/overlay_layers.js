/**
 * Intelligent Tracker - Multi-Layer Scrubber Overlay Manager.
 *
 * Coordinates concurrent detection run layers on the Video Scrubber canvas:
 * - Assigns distinct accessible color palettes (Cyan, Amber, Purple, Emerald, Rose)
 * - Persists checked layer selections per recording stem in localStorage
 * - Caches fetched detection streams across parent / _h264 codec switches
 * - Delegates toolbar rendering to OverlayLayerToolbar
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'intelligent_tracker_overlay_layers_v1';
  const MAX_STORED_RECORDINGS = 50;

  let currentFilename = null;
  let currentBaseStem = '';
  let currentRuns = [];
  let layerDescriptors = [];
  let activeRunIds = new Set();
  const streamCache = new Map();
  const inFlightStreams = new Map();
  const inFlightRuns = new Map();
  let jobEventsBound = false;

  function getPalettes() {
    return window.ScrubberOverlayRenderer?.PALETTES || window.ScrubberOverlay?.PALETTES || [
      { id: 'cyan', name: 'Cyan', stroke: '#06b6d4', fill: 'rgba(6, 182, 212, 0.16)', labelBg: 'rgba(8, 145, 178, 0.92)', text: '#ffffff' },
      { id: 'amber', name: 'Amber', stroke: '#f59e0b', fill: 'rgba(245, 158, 11, 0.16)', labelBg: 'rgba(180, 83, 9, 0.92)', text: '#ffffff' },
      { id: 'purple', name: 'Purple', stroke: '#a855f7', fill: 'rgba(168, 85, 247, 0.16)', labelBg: 'rgba(126, 34, 206, 0.92)', text: '#ffffff' },
      { id: 'emerald', name: 'Emerald', stroke: '#10b981', fill: 'rgba(16, 185, 129, 0.16)', labelBg: 'rgba(4, 120, 87, 0.92)', text: '#ffffff' },
      { id: 'rose', name: 'Rose', stroke: '#f43f5e', fill: 'rgba(244, 63, 94, 0.16)', labelBg: 'rgba(190, 18, 60, 0.92)', text: '#ffffff' },
    ];
  }

  function getBaseStem(filename) {
    if (!filename) return '';
    return String(filename).trim().replace(/_h264(\.[^.]+)$/i, '$1').replace(/\.[^.]+$/, '');
  }

  function isSameRecording(nameA, nameB) {
    return Boolean(nameA && nameB && getBaseStem(nameA) === getBaseStem(nameB));
  }

  function readStorageMap() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (_err) {
      return {};
    }
  }

  function loadSavedActiveIds(baseStem) {
    if (!baseStem) return null;
    const map = readStorageMap();
    return Array.isArray(map[baseStem]) ? map[baseStem] : null;
  }

  function saveActiveIds(baseStem, idsSet) {
    if (!baseStem) return;
    try {
      const map = readStorageMap();
      delete map[baseStem];
      map[baseStem] = Array.from(idsSet);
      const keys = Object.keys(map);
      if (keys.length > MAX_STORED_RECORDINGS) {
        keys.slice(0, keys.length - MAX_STORED_RECORDINGS).forEach((k) => delete map[k]);
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
    } catch (_err) {
      // Ignore storage quota or private-mode restrictions
    }
  }

  function formatRunDescriptor(run, runNum, palette) {
    const cfg = run.config || {};
    const detector = cfg.detector || 'yolov8';
    const conf = cfg.confidence !== undefined ? Number(cfg.confidence).toFixed(2) : '0.40';
    const stride = cfg.sample_rate || cfg.sampleRate || 1;
    const classesText = Array.isArray(cfg.classes) && cfg.classes.length > 0
      ? cfg.classes.join(', ')
      : `${detector} (all)`;
    return {
      runId: String(run.run_id),
      runNum,
      shortLabel: `R${runNum}`,
      classesText,
      label: `👁️ Run #${runNum}: ${classesText} (${palette.name})`,
      title: `Run #${runNum} · Classes: ${classesText} · Model: ${detector} · Conf ≥ ${conf} · Stride 1:${stride} (${palette.name})`,
      palette,
      run,
    };
  }

  function buildLayerDescriptors(runs) {
    if (!Array.isArray(runs) || runs.length === 0) return [];
    const palettes = getPalettes();
    const total = runs.length;
    const chronological = [];
    for (let idx = total - 1; idx >= 0; idx -= 1) {
      const run = runs[idx];
      if (!run || !run.run_id) continue;
      const runNum = total - idx;
      chronological.push(formatRunDescriptor(run, runNum, palettes[(runNum - 1) % palettes.length]));
    }
    return chronological;
  }

  async function fetchRunDetections(filename, runId) {
    const cacheKey = `${getBaseStem(filename)}::${runId}`;
    if (streamCache.has(cacheKey)) return streamCache.get(cacheKey);
    if (inFlightStreams.has(cacheKey)) return inFlightStreams.get(cacheKey);

    const promise = (async () => {
      try {
        const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/reports/${encodeURIComponent(runId)}/detections`);
        if (!resp.ok) return null;
        const data = await resp.json();
        const normalized = {
          frameDetections: Array.isArray(data.frame_detections) ? data.frame_detections : [],
          sourceResolution: Array.isArray(data.source_resolution) ? data.source_resolution : null,
          sourceFps: data.source_fps ?? null,
        };
        streamCache.set(cacheKey, normalized);
        return normalized;
      } catch (err) {
        console.debug('[OverlayLayers] Detection fetch error:', err);
        return null;
      } finally {
        inFlightStreams.delete(cacheKey);
      }
    })();

    inFlightStreams.set(cacheKey, promise);
    return promise;
  }

  async function pushDescriptorToCanvas(filename, expectedStem, desc) {
    const overlay = window.ScrubberOverlay;
    if (!overlay || typeof overlay.setLayer !== 'function') return;

    const stream = await fetchRunDetections(filename, desc.runId);
    if (!stream || currentBaseStem !== expectedStem || !activeRunIds.has(desc.runId)) return;
    overlay.setLayer(desc.runId, {
      runId: desc.runId,
      label: desc.label,
      shortLabel: desc.shortLabel,
      color: desc.palette,
      frameDetections: stream.frameDetections,
      sourceResolution: stream.sourceResolution,
    });
  }

  function applyActiveLayersToCanvas(filename, expectedStem) {
    const overlay = window.ScrubberOverlay;
    if (!overlay) return;

    const validIds = new Set(layerDescriptors.map((d) => d.runId));
    if (typeof overlay.getActiveLayerIds === 'function') {
      overlay.getActiveLayerIds().forEach((id) => {
        if (!String(id).startsWith('live:') && (!validIds.has(id) || !activeRunIds.has(id))) {
          overlay.removeLayer(id);
        }
      });
    }

    layerDescriptors.forEach((desc) => {
      if (activeRunIds.has(desc.runId)) {
        pushDescriptorToCanvas(filename, expectedStem, desc);
      } else {
        overlay.removeLayer?.(desc.runId);
      }
    });
  }

  function renderBar() {
    const activeJob = currentFilename ? window.VideoJobClient?.getActiveJob(currentFilename) : null;
    window.OverlayLayerToolbar?.renderToolbar({
      descriptors: layerDescriptors,
      activeRunIds,
      hasLiveJob: Boolean(activeJob && activeJob.job_type === 'analytics'),
      onToggle: toggleLayer,
      onSetAll: setAllLayers,
    });
  }

  function toggleLayer(runId) {
    const desc = layerDescriptors.find((d) => d.runId === String(runId));
    if (!desc || !currentFilename) return;

    if (activeRunIds.has(desc.runId)) {
      activeRunIds.delete(desc.runId);
      window.ScrubberOverlay?.removeLayer?.(desc.runId);
      window.OverlayLayerToolbar?.announceStatus(`Run #${desc.runNum} layer hidden`);
    } else {
      activeRunIds.add(desc.runId);
      pushDescriptorToCanvas(currentFilename, currentBaseStem, desc);
      window.OverlayLayerToolbar?.announceStatus(`Run #${desc.runNum} layer shown`);
    }
    saveActiveIds(currentBaseStem, activeRunIds);
    window.OverlayLayerToolbar?.updateChipStates(activeRunIds);
  }

  function setAllLayers(enabled) {
    if (!currentFilename || layerDescriptors.length === 0) return;
    if (enabled) {
      layerDescriptors.forEach((desc) => activeRunIds.add(desc.runId));
      window.OverlayLayerToolbar?.announceStatus('All detection layers shown');
    } else {
      activeRunIds.clear();
      window.OverlayLayerToolbar?.announceStatus('All detection layers hidden');
    }
    saveActiveIds(currentBaseStem, activeRunIds);
    window.OverlayLayerToolbar?.updateChipStates(activeRunIds);
    applyActiveLayersToCanvas(currentFilename, currentBaseStem);
  }

  function activateRun(filename, runId) {
    if (!filename || !runId) return;
    if (!isSameRecording(currentFilename, filename)) {
      ensureLoaded(filename, { activateRunId: runId });
      return;
    }
    const targetId = String(runId);
    const desc = layerDescriptors.find((d) => d.runId === targetId);
    if (!desc) {
      window.ScrubberOverlay?.loadDetections(filename, targetId);
      return;
    }
    if (!activeRunIds.has(targetId)) {
      activeRunIds.add(targetId);
      saveActiveIds(currentBaseStem, activeRunIds);
      window.OverlayLayerToolbar?.updateChipStates(activeRunIds);
      pushDescriptorToCanvas(currentFilename, currentBaseStem, desc);
      window.OverlayLayerToolbar?.announceStatus(`Run #${desc.runNum} layer shown`);
    }
  }

  function syncRuns(filename, runs, options = {}) {
    const stem = getBaseStem(filename);
    const prevStem = currentBaseStem;
    currentFilename = filename || null;
    currentBaseStem = stem;
    currentRuns = Array.isArray(runs) ? runs : [];

    if (prevStem && prevStem !== stem) {
      window.ScrubberOverlay?.clearLayers?.();
    }

    layerDescriptors = buildLayerDescriptors(currentRuns);
    if (!filename || layerDescriptors.length === 0) {
      activeRunIds = new Set();
      window.ScrubberOverlay?.clearLayers?.({ keepLive: true });
      renderBar();
      return;
    }

    const validIds = new Set(layerDescriptors.map((d) => d.runId));
    const saved = loadSavedActiveIds(stem);
    activeRunIds = saved === null
      ? new Set([String(currentRuns[0].run_id)])
      : new Set(saved.map(String).filter((id) => validIds.has(id)));

    if (options.activateRunId && validIds.has(String(options.activateRunId))) {
      activeRunIds.add(String(options.activateRunId));
    }

    saveActiveIds(stem, activeRunIds);
    renderBar();
    applyActiveLayersToCanvas(filename, stem);
  }

  async function ensureLoaded(filename, options = {}) {
    if (!filename) {
      syncRuns(null, []);
      return [];
    }
    const stem = getBaseStem(filename);
    if (stem !== currentBaseStem) {
      currentFilename = filename;
      currentBaseStem = stem;
      currentRuns = [];
      layerDescriptors = [];
      activeRunIds = new Set();
      renderBar();
    } else if (!options.force && currentRuns.length > 0) {
      currentFilename = filename;
      renderBar();
      applyActiveLayersToCanvas(filename, stem);
      return currentRuns;
    }

    if (!options.force && inFlightRuns.has(stem)) return inFlightRuns.get(stem);

    const promise = (async () => {
      try {
        const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/reports`);
        if (!resp.ok) return [];
        const runs = await resp.json();
        if (currentBaseStem && currentBaseStem !== stem) return [];
        syncRuns(filename, runs, options);
        return runs;
      } catch (err) {
        console.debug('[OverlayLayers] Failed loading run layers:', err);
        return [];
      } finally {
        inFlightRuns.delete(stem);
      }
    })();

    inFlightRuns.set(stem, promise);
    return promise;
  }

  function getNextPalette(filename) {
    const palettes = getPalettes();
    if (filename && isSameRecording(filename, currentFilename)) {
      return palettes[layerDescriptors.length % palettes.length];
    }
    return palettes[0];
  }

  function bindJobEvents() {
    if (jobEventsBound) return;
    jobEventsBound = true;
    window.addEventListener('video-job-event', (e) => {
      const { type, data: job } = e.detail || {};
      if (!job || job.job_type !== 'analytics' || !isSameRecording(currentFilename, job.filename)) return;
      if (type === 'job-finished' && job.status === 'completed' && currentFilename !== job.filename) {
        ensureLoaded(currentFilename, { force: true, activateRunId: job.result?.run_id || null });
      } else if (type === 'job-started' || type === 'job-finished') {
        renderBar();
      }
    });
  }

  function init() {
    bindJobEvents();
  }

  window.OverlayLayers = {
    init,
    syncRuns,
    ensureLoaded,
    toggleLayer,
    setAllLayers,
    activateRun,
    getNextPalette,
    getActiveRunIds: () => Array.from(activeRunIds),
    getLayerDescriptors: () => layerDescriptors.slice(),
    PALETTES: getPalettes(),
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
