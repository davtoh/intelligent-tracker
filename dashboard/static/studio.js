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
    activeCamera: 'cam_01',
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

  function drawOverlay(cursorPt) {
    window.StudioCanvas?.drawOverlay(studioState.ctx, studioState.canvas, studioState.mode, studioState.points, cursorPt);
  }

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

    loadCameraScenario(studioState.activeCamera);
    loadTopologyLinks();
    window.StudioOverlays?.loadCameraOverlays(studioState.activeCamera);
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

  async function saveZone(zoneData) {
    try {
      const res = await fetch('/api/scenarios/zones', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(zoneData),
      });
      if (res.ok) {
        updateStudioStatus(`Zone '${zoneData.name}' saved successfully.`);
        showToast('Zone Saved', `Spatial zone '${zoneData.name}' saved.`, 'success');
        loadCameraScenario(zoneData.camera_id);
      }
    } catch (err) {
      showToast('Error saving zone', err.message, 'error');
    }
  }

  async function deleteZone(camera_id, zone_name) {
    if (!confirm(`Delete zone '${zone_name}'?`)) return;
    try {
      const res = await fetch(`/api/scenarios/zones/${camera_id}/${encodeURIComponent(zone_name)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        updateStudioStatus(`Deleted zone '${zone_name}'.`);
        showToast('Zone Deleted', `Zone '${zone_name}' removed.`, 'info');
        loadCameraScenario(camera_id);
      }
    } catch (err) {
      showToast('Error deleting zone', err.message, 'error');
    }
  }

  async function saveTripwire(tripwireData) {
    try {
      const res = await fetch('/api/scenarios/tripwires', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(tripwireData),
      });
      if (res.ok) {
        updateStudioStatus(`Tripwire '${tripwireData.name}' saved successfully.`);
        showToast('Tripwire Saved', `Directional tripwire '${tripwireData.name}' saved.`, 'success');
        loadCameraScenario(tripwireData.camera_id);
      }
    } catch (err) {
      showToast('Error saving tripwire', err.message, 'error');
    }
  }

  async function deleteTripwire(camera_id, tripwire_name) {
    if (!confirm(`Delete tripwire '${tripwire_name}'?`)) return;
    try {
      const res = await fetch(`/api/scenarios/tripwires/${camera_id}/${encodeURIComponent(tripwire_name)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        updateStudioStatus(`Deleted tripwire '${tripwire_name}'.`);
        showToast('Tripwire Deleted', `Tripwire '${tripwire_name}' removed.`, 'info');
        loadCameraScenario(camera_id);
      }
    } catch (err) {
      showToast('Error deleting tripwire', err.message, 'error');
    }
  }

  async function saveHomographyCalibration(data) {
    try {
      const res = await fetch('/api/scenarios/homography', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (res.ok) {
        const result = await res.json();
        studioState.homography = result.homography;
        updateStudioStatus(`Homography calibrated for ${data.camera_id} (${data.metric_width}m x ${data.metric_height}m).`);
        showToast('Calibration Saved', `Homography calibrated for ${data.camera_id}.`, 'success');
        renderBEVMinimap();
      }
    } catch (err) {
      showToast('Calibration Error', err.message, 'error');
    }
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

  async function saveTopologyLink(linkData) {
    try {
      const res = await fetch('/api/topology/transitions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(linkData),
      });
      if (res.ok) {
        updateStudioStatus(`Transition link active.`);
        showToast('Transition Saved', 'Spatial transition link established.', 'success');
        loadTopologyLinks();
      }
    } catch (err) {
      showToast('Transition Error', err.message, 'error');
    }
  }

  async function deleteTopologyLink(linkId) {
    if (!confirm(`Remove transition link '${linkId}'?`)) return;
    try {
      const res = await fetch(`/api/topology/transitions/${encodeURIComponent(linkId)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showToast('Transition Removed', `Link '${linkId}' deleted.`, 'info');
        loadTopologyLinks();
      }
    } catch (err) {
      showToast('Transition Delete Error', err.message, 'error');
    }
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

  setInterval(() => {
    if (document.getElementById('tab-studio')?.classList.contains('active') || studioState.overlays.bev_minimap) {
      renderBEVMinimap();
    }
  }, 250);

  window.Studio = {
    init: initStudio,
    setMode: setStudioMode,
    deleteZone: deleteZone,
    deleteTripwire: deleteTripwire,
    deleteTopologyLink: deleteTopologyLink,
    renderBEV: renderBEVMinimap,
    searchJourney: (q) => window.JourneySearch?.search(q),
    exportJourney: (q) => window.JourneySearch?.exportVideo(q),
  };

  document.addEventListener('DOMContentLoaded', initStudio);
})();
