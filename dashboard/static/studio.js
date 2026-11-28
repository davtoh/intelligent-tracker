/**
 * Intelligent Tracker - World Scenario Studio, Space Awareness & Homography Controller.
 */

(function () {
  'use strict';

  const BEV_QUAD_MODES = ['all', 'selected', 'off'];
  const BEV_QUAD_LABELS = { all: '📐 BEV Quad: All', selected: '📐 BEV Quad: Selected', off: '📐 BEV Quad: Off' };

  const studioState = {
    activeCamera: null, mode: 'idle', bevQuadMode: 'all',
    points: [], zones: [], tripwires: [], homography: null, topologyLinks: [],
    overlays: { bboxes: true, track_ids: true, dwell_timers: true, velocity: false, zones: true, tripwires: true, heatmap: false, bev_minimap: false, hud_bar: true, clutter: false },
    overlayVisibility: { bboxes: true, track_ids: true, dwell_timers: true, velocity: false, zones: true, tripwires: true },
    canvas: null, ctx: null, bevCanvas: null,
  };

  const showToast = (t, b, type = 'info') => (typeof window.showToast === 'function' ? window.showToast(t, b, type) : console.warn(`[${type.toUpperCase()}] ${t}: ${b}`));

  function updateStudioStatus(msg, level = 'info') {
    const banner = document.getElementById('studio-status-banner');
    if (!banner) return;
    banner.textContent = msg;
    const show = level === 'warning' || level === 'error' || /error|warn|fail/i.test(String(msg || ''));
    if (banner.style) banner.style.display = show ? 'block' : 'none';
  }

  function setStudioMode(mode) {
    studioState.mode = mode;
    studioState.points = [];
    document.querySelectorAll('.studio-tool-btn').forEach((btn) => btn.classList.remove('active'));
    const cfg = {
      draw_zone: ['btn-mode-draw-zone', 'Mode: Draw Zone. Click vertices on video; double-click to close polygon.'],
      draw_tripwire: ['btn-mode-draw-tripwire', 'Mode: Draw Tripwire. Click start point, then click end point.'],
      calibrate_homography: ['btn-mode-homography', 'Mode: Calibrate Homography. Click 4 corners (TL -> TR -> BR -> BL).'],
    }[mode];
    if (cfg) { document.getElementById(cfg[0])?.classList.add('active'); updateStudioStatus(cfg[1]); }
    else updateStudioStatus('Ready. Select a tool to begin.');
    drawOverlay();
  }

  function setBevQuadMode(nextMode) {
    const mode = BEV_QUAD_MODES.includes(nextMode) ? nextMode : 'all';
    studioState.bevQuadMode = mode;
    const btn = document.getElementById('btn-studio-bev-quad-toggle');
    if (btn) {
      btn.textContent = BEV_QUAD_LABELS[mode];
      if (btn.dataset) btn.dataset.quadMode = mode;
      btn.setAttribute?.('aria-pressed', mode !== 'off' ? 'true' : 'false');
    }
    drawOverlay();
    return mode;
  }

  function resolveStudioTracks() {
    const tel = window.latestTelemetry;
    if (Array.isArray(tel?.active_tracks) && (!tel.camera_id || tel.camera_id === studioState.activeCamera)) {
      return { tracks: tel.active_tracks, sourceResolution: tel.source_resolution || tel.frame_size || null };
    }
    const vidTracks = window.ScrubberOverlay?.getCurrentTracks?.();
    return { tracks: Array.isArray(vidTracks) ? vidTracks : [], sourceResolution: null };
  }

  function clearStudioLiveImage() {
    if (window.StudioMedia?.clearStudioLiveImage) return window.StudioMedia.clearStudioLiveImage();
    const img = document.getElementById('studio-live-img');
    if (!img) return;
    if (img.dataset) delete img.dataset.activeStreamSrc;
    if (window.MediaEmptyState) window.MediaEmptyState.showEmpty(img, 'No Active Camera Feed', 'Select a camera or recorded video.');
    else { img.removeAttribute?.('src'); if (img.style) img.style.display = 'none'; }
  }

  function drawOverlay(cursorPt) {
    const { tracks, sourceResolution } = resolveStudioTracks();
    window.StudioCanvas?.drawOverlay(
      studioState.ctx, studioState.canvas, studioState.mode, studioState.points, cursorPt,
      {
        zones: studioState.zones, tripwires: studioState.tripwires,
        homography: studioState.homography, bevQuadMode: studioState.bevQuadMode,
        tracks, sourceResolution, overlayVisibility: studioState.overlayVisibility,
      }
    );
  }

  function applyStudioChannel(targetId, isVideo) {
    if (!targetId) return;
    (window.StudioMedia || window.StudioCanvas)?.attachStudioMedia?.(targetId, isVideo, isStudioTabActive());
    if (isVideo) clearStudioLiveImage();
    else window.StudioOverlays?.loadCameraOverlays(targetId);
  }

  function initStudio() {
    studioState.canvas = document.getElementById('studio-drawing-canvas');
    if (studioState.canvas) { studioState.ctx = studioState.canvas.getContext('2d'); setupCanvasListeners(); }
    studioState.bevCanvas = document.getElementById('bev-minimap-canvas');
    window.StudioOverlays?.init(() => studioState);
    window.StudioShapeEditor?.init(() => studioState, { drawOverlay, updateStatus: updateStudioStatus, showToast });
    bindStudioUI();
    window.WorldTacticalMinimapView?.bindPoseEditor?.(() => studioState.activeCamera);
    window.WorldMinimapInteractions?.bind?.(() => studioState.activeCamera);
    window.StudioOverlays?.bindOverlayToolbar();
    window.JourneySearch?.bind();
    loadStudioChannels().then(() => {
      if (studioState.activeCamera) {
        const isVideo = document.getElementById('studio-camera-select')?.selectedOptions?.[0]?.parentElement?.label === 'Recorded Videos';
        loadCameraScenario(studioState.activeCamera);
        applyStudioChannel(studioState.activeCamera, isVideo);
      } else { clearStudioLiveImage(); }
    });
    loadTopologyLinks();
    syncStudioTabState(isStudioTabActive());
  }

  async function loadStudioChannels() {
    const sel = document.getElementById('studio-camera-select');
    if (!sel) return;
    const [camRes, vidRes] = await Promise.allSettled([fetch('/api/cameras'), fetch('/api/videos')]);
    const cams = camRes.status === 'fulfilled' && camRes.value.ok ? await camRes.value.json() : [];
    const vids = vidRes.status === 'fulfilled' && vidRes.value.ok ? await vidRes.value.json() : [];
    sel.innerHTML = '';
    const appendGroup = (label, items, mapFn) => {
      if (!Array.isArray(items) || !items.length) return;
      const grp = document.createElement('optgroup');
      grp.label = label;
      items.forEach((it) => { const opt = mapFn(it); if (opt) grp.appendChild(opt); });
      if (grp.children.length) sel.appendChild(grp);
    };
    appendGroup('Camera Profiles', cams, (c) => c?.id && Object.assign(document.createElement('option'), { value: c.id, textContent: c.name ? `${c.name} (${c.id})` : c.id }));
    appendGroup('Recorded Videos', vids, (v) => v?.filename && Object.assign(document.createElement('option'), { value: v.filename, textContent: `🎬 ${v.filename}` }));
    if (!sel.options.length) sel.innerHTML = '<option value="">No cameras available</option>';
    const ctxRef = window.ActiveSourceContext?.get?.();
    const pref = studioState.activeCamera || ctxRef?.videoFilename || ctxRef?.cameraId || '';
    if (pref && [...sel.options].some((o) => o.value === pref)) { sel.value = pref; studioState.activeCamera = pref; }
    else studioState.activeCamera = sel.value || null;
  }

  function setupCanvasListeners() {
    window.StudioCanvas?.setupListeners(studioState.canvas, {
      onClick: (pt) => handleCanvasClick(pt),
      onMouseDown: (pt) => studioState.mode === 'idle' && window.StudioShapeEditor?.onMouseDown?.(pt),
      onMouseMove: (pt) => (studioState.mode === 'idle' && window.StudioShapeEditor?.onMouseMove?.(pt)) || drawOverlay(pt),
      onMouseUp: (pt) => studioState.mode === 'idle' && window.StudioShapeEditor?.onMouseUp?.(pt),
      onDblClick: () => handleCanvasDblClick(),
    });
  }

  function handleCanvasClick(pt) {
    if (studioState.mode === 'idle') return;
    if (studioState.mode === 'draw_zone') {
      studioState.points.push([pt.x, pt.y]); drawOverlay();
      updateStudioStatus(`Zone vertex #${studioState.points.length} placed at (${pt.x}, ${pt.y}). Double-click to close polygon.`);
    } else if (studioState.mode === 'draw_tripwire') {
      studioState.points.push([pt.x, pt.y]); drawOverlay();
      if (studioState.points.length === 2) window.ScenarioModals?.openTripwireModal(studioState.points);
      else updateStudioStatus(`Tripwire start point set at (${pt.x}, ${pt.y}). Click end point.`);
    } else if (studioState.mode === 'calibrate_homography' && studioState.points.length < 4) {
      studioState.points.push([pt.x, pt.y]); drawOverlay();
      const cornerNames = ['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left'];
      const nextIdx = studioState.points.length;
      if (nextIdx < 4) updateStudioStatus(`Corner ${nextIdx}/4 placed (${cornerNames[nextIdx - 1]}). Click corner #${nextIdx + 1} (${cornerNames[nextIdx]}).`);
      else { updateStudioStatus('All 4 ground corners selected! Enter metric dimensions and click Save Calibration.'); window.ScenarioModals?.openHomographyModal(studioState.points); }
    }
  }

  function handleCanvasDblClick() {
    if (studioState.mode !== 'draw_zone') return;
    if (studioState.points.length >= 3) window.ScenarioModals?.openZoneModal(studioState.points);
    else showToast('Validation Error', 'A polygonal zone requires at least 3 vertices.', 'warning');
  }

  async function loadCameraScenario(cameraId) {
    if (!cameraId) return;
    try {
      const res = await fetch(`/api/scenarios/${encodeURIComponent(cameraId)}`);
      if (!res.ok) return;
      const data = await res.json();
      studioState.zones = data.zones || [];
      studioState.tripwires = data.tripwires || [];
      studioState.homography = data.homography || null;
      window.StudioOverlays?.renderScenarioListUI();
      drawOverlay();
      renderBEVMinimap();
    } catch (err) { console.warn('Failed to load scenario:', err); }
  }

  function renderBEVMinimap() {
    if (window.WorldTacticalMinimapView) return window.WorldTacticalMinimapView.fetchAndRender(studioState.bevCanvas, studioState.activeCamera, studioState.homography, studioState.zones);
    window.BEVMinimap?.render(studioState.bevCanvas, studioState.homography, studioState.zones, studioState.activeCamera);
  }

  function requireActiveCamera() {
    if (studioState.activeCamera) return true;
    showToast('No Channel Selected', 'Select a camera or video channel first.', 'warning');
    return false;
  }

  async function studioRequest(url, options, okTitle, okBody, errTitle, onSuccess) {
    try {
      const res = await fetch(url, options);
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        if (okTitle) showToast(okTitle, okBody, options?.method === 'DELETE' ? 'info' : 'success');
        if (onSuccess) onSuccess(data);
      }
    } catch (err) { showToast(errTitle, err.message, 'error'); }
  }

  const jsonPost = (body) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  function saveZone(zoneData) {
    if (!zoneData?.camera_id && !requireActiveCamera()) return Promise.resolve();
    return studioRequest('/api/scenarios/zones', jsonPost(zoneData), 'Zone Saved', `Spatial zone '${zoneData.name}' saved.`, 'Error saving zone', () => {
      updateStudioStatus(`Zone '${zoneData.name}' saved successfully.`); loadCameraScenario(zoneData.camera_id);
    });
  }

  function deleteZone(camera_id, zone_name) {
    if (!camera_id || !confirm(`Delete zone '${zone_name}'?`)) return;
    return studioRequest(`/api/scenarios/zones/${encodeURIComponent(camera_id)}/${encodeURIComponent(zone_name)}`, { method: 'DELETE' },
      'Zone Deleted', `Zone '${zone_name}' removed.`, 'Error deleting zone', () => { updateStudioStatus(`Deleted zone '${zone_name}'.`); loadCameraScenario(camera_id); });
  }

  function saveTripwire(tripwireData) {
    if (!tripwireData?.camera_id && !requireActiveCamera()) return Promise.resolve();
    return studioRequest('/api/scenarios/tripwires', jsonPost(tripwireData), 'Tripwire Saved', `Directional tripwire '${tripwireData.name}' saved.`, 'Error saving tripwire', () => {
      updateStudioStatus(`Tripwire '${tripwireData.name}' saved successfully.`); loadCameraScenario(tripwireData.camera_id);
    });
  }

  function deleteTripwire(camera_id, tripwire_name) {
    if (!camera_id || !confirm(`Delete tripwire '${tripwire_name}'?`)) return;
    return studioRequest(`/api/scenarios/tripwires/${encodeURIComponent(camera_id)}/${encodeURIComponent(tripwire_name)}`, { method: 'DELETE' },
      'Tripwire Deleted', `Tripwire '${tripwire_name}' removed.`, 'Error deleting tripwire', () => { updateStudioStatus(`Deleted tripwire '${tripwire_name}'.`); loadCameraScenario(camera_id); });
  }

  function saveHomographyCalibration(data) {
    if (!data?.camera_id && !requireActiveCamera()) return Promise.resolve();
    return studioRequest('/api/scenarios/homography', jsonPost(data), 'Calibration Saved', `Homography calibrated for ${data.camera_id}.`, 'Calibration Error', (result) => {
      studioState.homography = result.homography || data;
      studioState.points = []; studioState.mode = 'idle';
      updateStudioStatus(`Homography calibrated for ${data.camera_id} (${data.metric_width}m x ${data.metric_height}m).`);
      drawOverlay(); renderBEVMinimap();
    });
  }

  async function loadTopologyLinks() {
    try {
      const res = await fetch('/api/topology/transitions');
      if (!res.ok) return;
      studioState.topologyLinks = await res.json();
      window.StudioOverlays?.renderTopologyLinksUI();
    } catch (err) { console.warn('Failed to load topology transitions:', err); }
  }

  const saveTopologyLink = (linkData) => studioRequest('/api/topology/transitions', jsonPost(linkData), 'Transition Saved', 'Spatial transition link established.', 'Transition Error', () => {
    updateStudioStatus('Transition link active.'); loadTopologyLinks();
  });

  function deleteTopologyLink(linkId) {
    if (!confirm(`Remove transition link '${linkId}'?`)) return;
    return studioRequest(`/api/topology/transitions/${encodeURIComponent(linkId)}`, { method: 'DELETE' }, 'Transition Removed', `Link '${linkId}' deleted.`, 'Transition Delete Error', () => loadTopologyLinks());
  }

  function mountStudioOverlayBar() {
    const bar = document.getElementById('studio-overlay-control-bar');
    if (!bar || !window.OverlayControlBar?.renderScrubberBar) return;
    window.OverlayControlBar.renderScrubberBar(bar, {
      descriptors: [], showFeaturePills: true, featureVisibility: studioState.overlayVisibility,
      onToggleFeature: (key, enabled) => { studioState.overlayVisibility[key] = Boolean(enabled); drawOverlay(); },
    });
  }

  function bindStudioUI() {
    document.getElementById('btn-mode-draw-zone')?.addEventListener('click', () => setStudioMode('draw_zone'));
    document.getElementById('btn-mode-draw-tripwire')?.addEventListener('click', () => setStudioMode('draw_tripwire'));
    document.getElementById('btn-mode-homography')?.addEventListener('click', () => setStudioMode('calibrate_homography'));
    document.getElementById('btn-studio-bev-quad-toggle')?.addEventListener('click', () => {
      setBevQuadMode(BEV_QUAD_MODES[(BEV_QUAD_MODES.indexOf(studioState.bevQuadMode) + 1) % BEV_QUAD_MODES.length]);
    });
    document.getElementById('btn-studio-clear')?.addEventListener('click', () => {
      setStudioMode('idle'); studioState.points = []; drawOverlay(); updateStudioStatus('Canvas cleared. Mode: Idle.');
    });
    (window.StudioMedia || window.StudioCanvas)?.bindFreezeControl?.(() => studioState.activeCamera);
    mountStudioOverlayBar();
    document.getElementById('studio-live-img')?.addEventListener?.('load', () => drawOverlay());
    document.getElementById('studio-video-player')?.addEventListener?.('loadedmetadata', () => drawOverlay());
    document.getElementById('studio-video-player')?.addEventListener?.('loadeddata', () => drawOverlay());
    document.getElementById('studio-video-player')?.addEventListener?.('seeked', () => drawOverlay());
    document.getElementById('studio-camera-select')?.addEventListener('change', (e) => {
      const rawVal = e.target.value;
      if (!rawVal) return;
      const isVideo = rawVal.startsWith('video:') || e.target.selectedOptions?.[0]?.parentElement?.label === 'Recorded Videos';
      const targetId = rawVal.startsWith('video:') ? rawVal.slice(6) : rawVal;
      studioState.activeCamera = targetId;
      window.ActiveSourceContext?.set?.(isVideo ? { kind: 'video', videoFilename: targetId } : { kind: 'camera', cameraId: targetId });
      updateStudioStatus(`Loaded scenario profile for '${targetId}'.`); loadCameraScenario(targetId); applyStudioChannel(targetId, isVideo);
    });
    document.getElementById('btn-add-transition-link')?.addEventListener('click', () => window.ScenarioModals?.openTransitionLinkModal(studioState.activeCamera));
    window.ScenarioModals?.init({
      onSaveZone: (data) => requireActiveCamera() && saveZone({ ...data, camera_id: studioState.activeCamera }),
      onSaveTripwire: (data) => requireActiveCamera() && saveTripwire({ ...data, camera_id: studioState.activeCamera }),
      onSaveHomography: (data) => requireActiveCamera() && saveHomographyCalibration({ ...data, camera_id: studioState.activeCamera }),
      onSaveTransition: (data) => saveTopologyLink(data),
      onCancel: () => setStudioMode('idle'),
    });
  }

  let minimapTimer = null;
  const isStudioTabActive = () => Boolean(document.getElementById('tab-studio')?.classList?.contains('active'));
  function startMinimapLoop() {
    if (minimapTimer !== null) return;
    minimapTimer = setInterval(() => {
      if (isStudioTabActive()) drawOverlay();
      if (isStudioTabActive() || studioState.overlays.bev_minimap) renderBEVMinimap();
    }, 250);
  }
  function stopMinimapLoop() { if (minimapTimer !== null) { clearInterval(minimapTimer); minimapTimer = null; } }
  function syncStudioTabState(isActive) {
    const active = typeof isActive === 'boolean' ? isActive : isStudioTabActive();
    if (active) {
      if (studioState.activeCamera) {
        const isVideo = document.getElementById('studio-camera-select')?.selectedOptions?.[0]?.parentElement?.label === 'Recorded Videos';
        (window.StudioMedia || window.StudioCanvas)?.attachStudioMedia?.(studioState.activeCamera, isVideo, true);
        drawOverlay();
      }
      renderBEVMinimap(); startMinimapLoop();
    } else { stopMinimapLoop(); }
  }
  window.addEventListener('tab-changed', (ev) => syncStudioTabState(ev?.detail?.activeTab ? ev.detail.activeTab === 'tab-studio' : isStudioTabActive()));
  window.Studio = {
    init: initStudio, setMode: setStudioMode, setBevQuadMode, getBevQuadMode: () => studioState.bevQuadMode,
    drawOverlay, saveHomographyCalibration, deleteZone, deleteTripwire, deleteTopologyLink,
    loadStudioChannels, renderBEV: renderBEVMinimap, startMinimapLoop, stopMinimapLoop,
    syncStudioTabState, syncTabVisibility: syncStudioTabState,
    selectZoneById: (id) => window.StudioCanvas?.selectZoneById?.(id, studioState, { updateStatus: updateStudioStatus, drawOverlay }),
    searchJourney: (q) => window.JourneySearch?.search(q), exportJourney: (q) => window.JourneySearch?.exportVideo(q),
  };
  document.addEventListener('DOMContentLoaded', initStudio);
})();
