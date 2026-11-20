/**
 * Intelligent Tracker - World Scenario Studio, Space Awareness & Homography Controller.
 * Milestone 8 Implementation.
 * 
 * Coordinates:
 * - Studio Canvas polygon and tripwire drawing modes
 * - 2D Bird's-Eye-View (BEV) minimap rendering
 * - Dedicated in-page modal dialog forms
 * - Trajectory Journey Search & Video Export
 */

(function () {
  'use strict';

  const studioState = {
    activeCamera: null,
    mode: 'idle',
    points: [],
    zones: [],
    tripwires: [],
    homography: null,
    topologyLinks: [],
    overlays: {
      bboxes: true, track_ids: true, dwell_timers: true, velocity: true,
      zones: true, tripwires: true, heatmap: false, bev_minimap: false,
      hud_bar: true, toast_prompts: true,
    },
    canvas: null,
    ctx: null,
    bevCanvas: null,
  };

  function showToast(title, body, type = 'info') {
    if (typeof window.showToast === 'function') {
      window.showToast(title, body, type);
    } else {
      console.warn(`[${type.toUpperCase()}] ${title}: ${body}`);
    }
  }

  function updateStudioStatus(msg) {
    const banner = document.getElementById('studio-status-banner');
    if (banner) banner.textContent = msg;
  }

  function setStudioMode(mode) {
    studioState.mode = mode;
    studioState.points = [];
    const banner = document.getElementById('studio-status-banner');

    document.querySelectorAll('.studio-tool-btn').forEach(btn => btn.classList.remove('active'));
    if (mode === 'draw_zone') {
      document.getElementById('btn-mode-draw-zone')?.classList.add('active');
      if (banner) banner.textContent = 'Mode: Draw Zone. Click vertices on video; double-click to close polygon.';
    } else if (mode === 'draw_tripwire') {
      document.getElementById('btn-mode-draw-tripwire')?.classList.add('active');
      if (banner) banner.textContent = 'Mode: Draw Tripwire. Click start point, then click end point.';
    } else if (mode === 'calibrate_homography') {
      document.getElementById('btn-mode-homography')?.classList.add('active');
      if (banner) banner.textContent = 'Mode: Calibrate Homography. Click 4 corners (TL -> TR -> BR -> BL).';
    } else {
      if (banner) banner.textContent = 'Ready. Select a tool to begin.';
    }
    drawOverlay();
  }

  function clearStudioLiveImage() {
    const img = document.getElementById('studio-live-img');
    if (img) { if (img.dataset) delete img.dataset.activeStreamSrc; img.removeAttribute?.('src'); img.src = ''; }
  }
  function drawOverlay(cursorPt) { window.StudioCanvas?.drawOverlay(studioState.ctx, studioState.canvas, studioState.mode, studioState.points, cursorPt); }

  function initStudio() {
    studioState.canvas = document.getElementById('studio-drawing-canvas');
    if (studioState.canvas) {
      studioState.ctx = studioState.canvas.getContext('2d');
      setupCanvasListeners();
    }
    studioState.bevCanvas = document.getElementById('bev-minimap-canvas');

    window.StudioOverlays?.init(() => studioState);
    bindStudioUI();
    window.StudioOverlays?.bindOverlayToolbar();
    window.JourneySearch?.bind();

    loadStudioChannels().then(() => {
      if (studioState.activeCamera) {
        const isVideo = document.getElementById('studio-camera-select')?.selectedOptions?.[0]?.parentElement?.label === 'Recorded Videos';
        loadCameraScenario(studioState.activeCamera);
        if (isVideo) clearStudioLiveImage();
        else window.StudioOverlays?.loadCameraOverlays(studioState.activeCamera);
      }
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
    if (studioState.activeCamera && [...sel.options].some((o) => o.value === studioState.activeCamera)) sel.value = studioState.activeCamera;
    else studioState.activeCamera = sel.value || null;
  }

  function setupCanvasListeners() {
    window.StudioCanvas?.setupListeners(studioState.canvas, {
      onClick: (pt) => handleCanvasClick(pt),
      onMouseMove: (pt) => drawOverlay(pt),
      onDblClick: () => handleCanvasDblClick(),
    });
  }

  function handleCanvasClick(pt) {
    if (studioState.mode === 'idle') return;

    if (studioState.mode === 'draw_zone') {
      studioState.points.push([pt.x, pt.y]);
      drawOverlay();
      updateStudioStatus(`Zone vertex #${studioState.points.length} placed at (${pt.x}, ${pt.y}). Double-click to close polygon.`);
    } else if (studioState.mode === 'draw_tripwire') {
      studioState.points.push([pt.x, pt.y]);
      drawOverlay();
      if (studioState.points.length === 2) {
        window.ScenarioModals?.openTripwireModal(studioState.points);
      } else {
        updateStudioStatus(`Tripwire start point set at (${pt.x}, ${pt.y}). Click end point.`);
      }
    } else if (studioState.mode === 'calibrate_homography') {
      if (studioState.points.length < 4) {
        studioState.points.push([pt.x, pt.y]);
        drawOverlay();
        const cornerNames = ['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left'];
        const nextIdx = studioState.points.length;
        if (nextIdx < 4) {
          updateStudioStatus(`Corner ${nextIdx}/4 placed (${cornerNames[nextIdx - 1]}). Click corner #${nextIdx + 1} (${cornerNames[nextIdx]}).`);
        } else {
          updateStudioStatus('All 4 ground corners selected! Enter metric dimensions and click Save Calibration.');
          window.ScenarioModals?.openHomographyModal(studioState.points);
        }
      }
    }
  }

  function handleCanvasDblClick() {
    if (studioState.mode === 'draw_zone') {
      if (studioState.points.length >= 3) {
        window.ScenarioModals?.openZoneModal(studioState.points);
      } else {
        showToast('Validation Error', 'A polygonal zone requires at least 3 vertices.', 'warning');
      }
    }
  }

  async function loadCameraScenario(cameraId) {
    try {
      const res = await fetch(`/api/scenarios/${cameraId}`);
      if (!res.ok) return;
      const data = await res.json();
      studioState.zones = data.zones || [];
      studioState.tripwires = data.tripwires || [];
      studioState.homography = data.homography || null;

      window.StudioOverlays?.renderScenarioListUI();
      renderBEVMinimap();
    } catch (err) {
      console.warn('Failed to load scenario:', err);
    }
  }

  function renderBEVMinimap() {
    window.BEVMinimap?.render(studioState.bevCanvas, studioState.homography, studioState.zones, studioState.activeCamera);
  }

  async function studioRequest(url, options, okTitle, okBody, errTitle, onSuccess) {
    try {
      const res = await fetch(url, options);
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        if (okTitle) showToast(okTitle, okBody, options?.method === 'DELETE' ? 'info' : 'success');
        if (onSuccess) onSuccess(data);
      }
    } catch (err) {
      showToast(errTitle, err.message, 'error');
    }
  }

  function saveZone(zoneData) {
    return studioRequest('/api/scenarios/zones', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(zoneData),
    }, 'Zone Saved', `Spatial zone '${zoneData.name}' saved.`, 'Error saving zone', () => {
      updateStudioStatus(`Zone '${zoneData.name}' saved successfully.`);
      loadCameraScenario(zoneData.camera_id);
    });
  }

  function deleteZone(camera_id, zone_name) {
    if (!confirm(`Delete zone '${zone_name}'?`)) return;
    return studioRequest(`/api/scenarios/zones/${camera_id}/${encodeURIComponent(zone_name)}`, {
      method: 'DELETE',
    }, 'Zone Deleted', `Zone '${zone_name}' removed.`, 'Error deleting zone', () => {
      updateStudioStatus(`Deleted zone '${zone_name}'.`);
      loadCameraScenario(camera_id);
    });
  }

  function saveTripwire(tripwireData) {
    return studioRequest('/api/scenarios/tripwires', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(tripwireData),
    }, 'Tripwire Saved', `Directional tripwire '${tripwireData.name}' saved.`, 'Error saving tripwire', () => {
      updateStudioStatus(`Tripwire '${tripwireData.name}' saved successfully.`);
      loadCameraScenario(tripwireData.camera_id);
    });
  }

  function deleteTripwire(camera_id, tripwire_name) {
    if (!confirm(`Delete tripwire '${tripwire_name}'?`)) return;
    return studioRequest(`/api/scenarios/tripwires/${camera_id}/${encodeURIComponent(tripwire_name)}`, {
      method: 'DELETE',
    }, 'Tripwire Deleted', `Tripwire '${tripwire_name}' removed.`, 'Error deleting tripwire', () => {
      updateStudioStatus(`Deleted tripwire '${tripwire_name}'.`);
      loadCameraScenario(camera_id);
    });
  }

  function saveHomographyCalibration(data) {
    return studioRequest('/api/scenarios/homography', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }, 'Calibration Saved', `Homography calibrated for ${data.camera_id}.`, 'Calibration Error', (result) => {
      studioState.homography = result.homography;
      updateStudioStatus(`Homography calibrated for ${data.camera_id} (${data.metric_width}m x ${data.metric_height}m).`);
      renderBEVMinimap();
    });
  }

  async function loadTopologyLinks() {
    try {
      const res = await fetch('/api/topology/transitions');
      if (!res.ok) return;
      studioState.topologyLinks = await res.json();
      window.StudioOverlays?.renderTopologyLinksUI();
    } catch (err) {
      console.warn('Failed to load topology transitions:', err);
    }
  }

  function saveTopologyLink(linkData) {
    return studioRequest('/api/topology/transitions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(linkData),
    }, 'Transition Saved', 'Spatial transition link established.', 'Transition Error', () => {
      updateStudioStatus('Transition link active.');
      loadTopologyLinks();
    });
  }

  function deleteTopologyLink(linkId) {
    if (!confirm(`Remove transition link '${linkId}'?`)) return;
    return studioRequest(`/api/topology/transitions/${encodeURIComponent(linkId)}`, {
      method: 'DELETE',
    }, 'Transition Removed', `Link '${linkId}' deleted.`, 'Transition Delete Error', () => loadTopologyLinks());
  }

  function bindStudioUI() {
    document.getElementById('btn-mode-draw-zone')?.addEventListener('click', () => setStudioMode('draw_zone'));
    document.getElementById('btn-mode-draw-tripwire')?.addEventListener('click', () => setStudioMode('draw_tripwire'));
    document.getElementById('btn-mode-homography')?.addEventListener('click', () => setStudioMode('calibrate_homography'));
    document.getElementById('btn-studio-clear')?.addEventListener('click', () => {
      setStudioMode('idle');
      studioState.points = [];
      drawOverlay();
      updateStudioStatus('Canvas cleared. Mode: Idle.');
    });

    document.getElementById('studio-camera-select')?.addEventListener('change', (e) => {
      const targetId = e.target.value;
      if (!targetId) return;
      studioState.activeCamera = targetId;
      const isVideo = e.target.selectedOptions?.[0]?.parentElement?.label === 'Recorded Videos';
      const img = document.getElementById('studio-live-img');
      if (isVideo) clearStudioLiveImage();
      else if (img) {
        const streamBase = `/stream/${encodeURIComponent(targetId)}`;
        if (img.dataset) img.dataset.activeStreamSrc = streamBase;
        if (isStudioTabActive()) img.src = `${streamBase}?t=${Date.now()}`;
      }
      updateStudioStatus(`Loaded scenario profile for '${targetId}'.`);
      loadCameraScenario(targetId);
      if (!isVideo) window.StudioOverlays?.loadCameraOverlays(targetId);
    });
    document.getElementById('btn-add-transition-link')?.addEventListener('click', () => {
      window.ScenarioModals?.openTransitionLinkModal(studioState.activeCamera);
    });

    window.ScenarioModals?.init({
      onSaveZone: (data) => saveZone({ ...data, camera_id: studioState.activeCamera }),
      onSaveTripwire: (data) => saveTripwire({ ...data, camera_id: studioState.activeCamera }),
      onSaveHomography: (data) => saveHomographyCalibration({ ...data, camera_id: studioState.activeCamera }),
      onSaveTransition: (data) => saveTopologyLink(data),
      onCancel: () => setStudioMode('idle'),
    });
  }

  let minimapTimer = null;
  const isStudioTabActive = () => Boolean(document.getElementById('tab-studio')?.classList?.contains('active'));
  function startMinimapLoop() {
    if (minimapTimer !== null) return;
    minimapTimer = setInterval(() => {
      if (isStudioTabActive() || studioState.overlays.bev_minimap) renderBEVMinimap();
    }, 250);
  }
  function stopMinimapLoop() {
    if (minimapTimer === null) return;
    clearInterval(minimapTimer);
    minimapTimer = null;
  }
  function syncStudioTabState(isActive) {
    const active = typeof isActive === 'boolean' ? isActive : isStudioTabActive();
    if (active) { renderBEVMinimap(); startMinimapLoop(); } else { stopMinimapLoop(); }
  }
  window.addEventListener('tab-changed', (ev) => {
    const activeTab = ev?.detail?.activeTab;
    syncStudioTabState(activeTab ? activeTab === 'tab-studio' : isStudioTabActive());
  });

  window.Studio = {
    init: initStudio, setMode: setStudioMode, deleteZone: deleteZone,
    deleteTripwire: deleteTripwire, deleteTopologyLink: deleteTopologyLink,
    renderBEV: renderBEVMinimap, startMinimapLoop: startMinimapLoop,
    stopMinimapLoop: stopMinimapLoop, syncStudioTabState: syncStudioTabState,
    syncTabVisibility: syncStudioTabState,
    searchJourney: (q) => window.JourneySearch?.search(q),
    exportJourney: (q) => window.JourneySearch?.exportVideo(q),
  };

  document.addEventListener('DOMContentLoaded', initStudio);
})();
