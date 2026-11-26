/**
 * Intelligent Tracker - Shared #modal-snapshot-view Canvas Overlay & Reset Helper.
 * Manages UnifiedCanvasOverlay, OverlayControlBar, ResizeObserver, and scenario
 * zone/tripwire hydration for alert snapshots, with clean reset for #timeline views.
 */
(function () {
  'use strict';

  const DEFAULT_VISIBILITY = {
    bboxes: true, track_ids: true, dwell_timers: true,
    velocity: false, zones: true, tripwires: true,
  };

  const state = {
    activeEvent: null,
    hydratedZones: [],
    hydratedTripwires: [],
    hydrationToken: 0,
    resizeObserver: null,
    featureVisibility: { ...DEFAULT_VISIBILITY },
  };

  function disconnectResizeObserver() {
    if (state.resizeObserver) {
      try { state.resizeObserver.disconnect(); } catch (_err) { /* noop */ }
      state.resizeObserver = null;
    }
  }

  function observeStage(img) {
    disconnectResizeObserver();
    if (typeof window.ResizeObserver !== 'function' || !img) return;
    const target = img.parentElement || img;
    state.resizeObserver = new window.ResizeObserver(() => {
      if (state.activeEvent) render();
    });
    state.resizeObserver.observe(target);
  }

  function buildTracksForEvent(ev) {
    const bbox = ev?.bbox || ev?.metadata?.bbox;
    if (!Array.isArray(bbox) || bbox.length < 4) return [];
    return [{
      bbox,
      id: ev.track_id ?? ev.metadata?.track_id,
      entity_name: ev.entity_name || ev.name || ev.suggested_name,
      label: ev.event_type || 'alert',
      confidence: ev.confidence,
    }];
  }

  function render() {
    const img = document.getElementById('snapshot-modal-img');
    const canvas = document.getElementById('snapshot-modal-canvas');
    const U = window.UnifiedCanvasOverlay;
    if (!img || !canvas || !U) return;
    const ctx = canvas.getContext?.('2d');
    if (!ctx) return;
    const imgRect = img.getBoundingClientRect?.() || { width: img.naturalWidth || 640, height: img.naturalHeight || 360, left: 0, top: 0 };
    const stageRect = img.parentElement?.getBoundingClientRect?.() || imgRect;
    const mediaW = img.naturalWidth || imgRect.width || 640;
    const mediaH = img.naturalHeight || imgRect.height || 360;
    const stageW = stageRect.width || mediaW;
    const stageH = stageRect.height || mediaH;
    U.syncCanvasDpr(canvas, ctx, stageW, stageH, window.devicePixelRatio || 1);
    const box = U.computeContainBox(imgRect, stageRect, mediaW, mediaH);
    const ev = state.activeEvent || {};
    const scales = U.resolveScaleFactors(box.renderW, box.renderH, ev.source_resolution || ev.metadata?.source_resolution, mediaW, mediaH);
    const zones = Array.isArray(ev.zones) && ev.zones.length ? ev.zones : state.hydratedZones;
    const tripwires = Array.isArray(ev.tripwires) && ev.tripwires.length ? ev.tripwires : state.hydratedTripwires;
    U.renderScene(ctx, {
      clear: true,
      clearWidth: stageW,
      clearHeight: stageH,
      visibility: state.featureVisibility,
      transform: { offsetX: box.offsetX, offsetY: box.offsetY, scaleX: scales.scaleX, scaleY: scales.scaleY },
      tracks: buildTracksForEvent(ev),
      zones,
      tripwires,
    });
  }

  async function hydrateScenario(ev, token) {
    const camId = String(ev?.camera_id || '').trim();
    if (!camId || typeof fetch !== 'function') return;
    const hasZones = Array.isArray(ev.zones) && ev.zones.length > 0;
    const hasTripwires = Array.isArray(ev.tripwires) && ev.tripwires.length > 0;
    if (hasZones && hasTripwires) return;
    try {
      const res = await fetch(`/api/scenarios/${encodeURIComponent(camId)}`);
      if (!res?.ok || token !== state.hydrationToken) return;
      const data = await res.json();
      if (token !== state.hydrationToken) return;
      if (!hasZones && Array.isArray(data?.zones)) state.hydratedZones = data.zones;
      if (!hasTripwires && Array.isArray(data?.tripwires)) state.hydratedTripwires = data.tripwires;
      render();
    } catch (_err) {
      // Non-fatal: alert snapshot still displays image & bbox
    }
  }

  function reset() {
    state.hydrationToken += 1;
    state.activeEvent = null;
    state.hydratedZones = [];
    state.hydratedTripwires = [];
    disconnectResizeObserver();
    const img = document.getElementById('snapshot-modal-img');
    if (img) img.onload = null;
    const canvas = document.getElementById('snapshot-modal-canvas');
    const ctx = canvas?.getContext?.('2d');
    if (ctx && canvas) ctx.clearRect?.(0, 0, canvas.width || 9999, canvas.height || 9999);
    const controlsEl = document.getElementById('snapshot-modal-controls');
    if (controlsEl) { controlsEl.innerHTML = ''; controlsEl.hidden = true; }
  }

  function open(ev, src, opts = {}) {
    if (!ev || !src) return;
    reset();
    const token = state.hydrationToken;
    state.activeEvent = ev;
    if (opts.visibility && typeof opts.visibility === 'object') {
      state.featureVisibility = { ...state.featureVisibility, ...opts.visibility };
    }
    window.AlertsAdmin?.syncSnapshotDownloadButton?.(src, ev);
    const modal = document.getElementById('modal-snapshot-view');
    const img = document.getElementById('snapshot-modal-img');
    const metaEl = document.getElementById('snapshot-modal-meta');
    const controlsEl = document.getElementById('snapshot-modal-controls');
    if (img) { img.onload = () => render(); img.src = src; observeStage(img); }
    if (metaEl) metaEl.textContent = `${ev.event_type || 'alert'} · ${ev.camera_id || 'System'}${ev.zone_id ? ` (${ev.zone_id})` : ''}`;
    if (controlsEl && window.OverlayControlBar?.mount) {
      controlsEl.hidden = false;
      window.OverlayControlBar.mount({
        container: controlsEl, variant: 'scrubber', descriptors: [], showFeaturePills: true,
        featureVisibility: state.featureVisibility,
        onToggleFeature: (key, next) => { state.featureVisibility[key] = Boolean(next); render(); },
      });
    }
    if (modal) modal.style.display = 'flex';
    if (img?.complete && img?.naturalWidth > 0) render();
    hydrateScenario(ev, token);
  }

  window.SnapshotModalOverlay = {
    state, open, render, reset,
    getVisibility: () => ({ ...state.featureVisibility }),
    setVisibility: (next) => { state.featureVisibility = { ...state.featureVisibility, ...(next || {}) }; },
  };
})();
