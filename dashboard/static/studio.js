/**
 * Intelligent Tracker - Scenario Studio Controller.
 * Coordinates interactive zone/tripwire ROI drawing, homography calibration,
 * and delegates BEV minimap rendering and trajectory journey tracking to submodules.
 */

window.Studio = window.Studio || {};

(function () {
  'use strict';

  const escapeHtml = window.escapeHtml || (s => s);
  const showToast = window.showToast || ((m, t) => console.log(m, t));

  const studioState = {
    activeCamera: 'cam_01',
    mode: 'idle', // 'idle' | 'polygon' | 'tripwire' | 'homography'
    currentPoints: [],
    zones: [],
    tripwires: [],
    homography: null,
    topologyLinks: [],
    overlays: {
      heatmaps: true,
      tripwires: true,
      zones: true,
      bboxes: true,
      bev_minimap: false,
    },
    canvas: null,
    ctx: null,
    bevCanvas: null,
    bevCtx: null,
  };

  let pendingZonePolygon = null;
  let pendingTripwirePoints = null;
  let pendingHomographyPoints = null;
  let studioModalsInitialized = false;

  function initStudio() {
    studioState.canvas = document.getElementById('studio-drawing-canvas');
    if (studioState.canvas) {
      studioState.ctx = studioState.canvas.getContext('2d');
      setupCanvasEventListeners(studioState.canvas);
    }

    studioState.bevCanvas = document.getElementById('bev-minimap-canvas');
    if (studioState.bevCanvas) {
      studioState.bevCtx = studioState.bevCanvas.getContext('2d');
    }

    bindStudioUI();
    bindOverlayToolbar();
    if (window.TrackerApp.Topology?.bindJourneySearch) {
      window.TrackerApp.Topology.bindJourneySearch();
    }
    initStudioModals();

    const camSelect = document.getElementById('camera-select');
    if (camSelect && camSelect.value) {
      studioState.activeCamera = camSelect.value;
    }
    loadCameraScenario(studioState.activeCamera);
    loadCameraOverlays(studioState.activeCamera);
    if (window.TrackerApp.Topology?.loadLinks) {
      window.TrackerApp.Topology.loadLinks();
    }
  }

  function setupCanvasEventListeners(canvas) {
    canvas.addEventListener('click', onCanvasClick);
    canvas.addEventListener('mousemove', onCanvasMouseMove);
    canvas.addEventListener('dblclick', onCanvasDblClick);
  }

  function getCanvasCoords(evt, canvas) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = 640 / canvas.clientWidth;
    const scaleY = 480 / canvas.clientHeight;
    return [
      Math.round((evt.clientX - rect.left) * scaleX),
      Math.round((evt.clientY - rect.top) * scaleY),
    ];
  }

  function onCanvasClick(evt) {
    if (studioState.mode === 'idle') return;
    const pt = getCanvasCoords(evt, studioState.canvas);
    studioState.currentPoints.push(pt);

    if (studioState.mode === 'tripwire') {
      if (studioState.currentPoints.length === 2) {
        const line = [...studioState.currentPoints];
        studioState.currentPoints = [];
        setStudioMode('idle');
        openTripwireModal(line);
      }
    } else if (studioState.mode === 'homography') {
      if (studioState.currentPoints.length === 4) {
        const pts = [...studioState.currentPoints];
        studioState.currentPoints = [];
        setStudioMode('idle');
        openHomographyModal(pts);
      }
    }
    drawStudioOverlay();
  }

  function onCanvasMouseMove(evt) {
    if (studioState.mode === 'idle' || studioState.currentPoints.length === 0) return;
    const pt = getCanvasCoords(evt, studioState.canvas);
    drawStudioOverlay(pt);
  }

  function onCanvasDblClick(evt) {
    if (studioState.mode === 'polygon') {
      evt.preventDefault();
      if (studioState.currentPoints.length >= 3) {
        const poly = [...studioState.currentPoints];
        studioState.currentPoints = [];
        setStudioMode('idle');
        openZoneModal(poly);
      } else {
        updateStudioStatus('A zone polygon requires at least 3 vertices.');
      }
      drawStudioOverlay();
    }
  }

  function drawStudioOverlay(cursorPt) {
    const canvas = studioState.canvas;
    const ctx = studioState.ctx;
    if (!canvas || !ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const scaleX = canvas.width / 640;
    const scaleY = canvas.height / 480;

    // 1. Draw Existing Zones
    if (studioState.zones) {
      studioState.zones.forEach((z) => {
        if (!z.polygon || z.polygon.length < 3) return;
        ctx.beginPath();
        ctx.moveTo(z.polygon[0][0] * scaleX, z.polygon[0][1] * scaleY);
        for (let i = 1; i < z.polygon.length; i++) {
          ctx.lineTo(z.polygon[i][0] * scaleX, z.polygon[i][1] * scaleY);
        }
        ctx.closePath();
        ctx.fillStyle = 'rgba(0, 200, 100, 0.25)';
        ctx.fill();
        ctx.strokeStyle = '#00ff88';
        ctx.lineWidth = 2;
        ctx.stroke();

        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 12px Inter, sans-serif';
        ctx.fillText(z.name, z.polygon[0][0] * scaleX + 5, z.polygon[0][1] * scaleY + 15);
      });
    }

    // 2. Draw Existing Tripwires
    if (studioState.tripwires) {
      studioState.tripwires.forEach((tw) => {
        if (!tw.line_segment || tw.line_segment.length < 2) return;
        const p1 = tw.line_segment[0];
        const p2 = tw.line_segment[1];
        ctx.beginPath();
        ctx.moveTo(p1[0] * scaleX, p1[1] * scaleY);
        ctx.lineTo(p2[0] * scaleX, p2[1] * scaleY);
        ctx.strokeStyle = '#00e5ff';
        ctx.lineWidth = 3;
        ctx.stroke();

        ctx.fillStyle = '#00e5ff';
        ctx.beginPath();
        ctx.arc(p1[0] * scaleX, p1[1] * scaleY, 5, 0, Math.PI * 2);
        ctx.arc(p2[0] * scaleX, p2[1] * scaleY, 5, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 12px Inter, sans-serif';
        ctx.fillText(tw.name, (p1[0] + p2[0]) / 2 * scaleX, (p1[1] + p2[1]) / 2 * scaleY - 8);
      });
    }

    // 3. Draw Points Currently Being Placed
    if (studioState.currentPoints.length > 0) {
      ctx.strokeStyle = '#facc15';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(studioState.currentPoints[0][0] * scaleX, studioState.currentPoints[0][1] * scaleY);
      for (let i = 1; i < studioState.currentPoints.length; i++) {
        ctx.lineTo(studioState.currentPoints[i][0] * scaleX, studioState.currentPoints[i][1] * scaleY);
      }
      if (cursorPt) {
        ctx.lineTo(cursorPt[0] * scaleX, cursorPt[1] * scaleY);
      }
      if (studioState.mode === 'polygon' && studioState.currentPoints.length >= 3 && !cursorPt) {
        ctx.closePath();
      }
      ctx.stroke();

      studioState.currentPoints.forEach((pt, idx) => {
        ctx.fillStyle = '#facc15';
        ctx.beginPath();
        ctx.arc(pt[0] * scaleX, pt[1] * scaleY, 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#000000';
        ctx.font = 'bold 10px monospace';
        ctx.fillText(`${idx + 1}`, pt[0] * scaleX - 3, pt[1] * scaleY + 3);
      });
    }
  }

  function setStudioMode(mode) {
    studioState.mode = mode;
    studioState.currentPoints = [];
    document.querySelectorAll('.studio-tool-btn').forEach((btn) => btn.classList.remove('active'));

    const btnIdMap = {
      polygon: 'btn-tool-zone',
      tripwire: 'btn-tool-tripwire',
      homography: 'btn-tool-homography',
      idle: 'btn-tool-select',
    };
    const activeBtn = document.getElementById(btnIdMap[mode]);
    if (activeBtn) activeBtn.classList.add('active');

    const statusMap = {
      idle: 'Ready. Select a tool above to configure zones, tripwires, or calibration.',
      polygon: 'Polygon Mode: Click to place vertices. Double-click to complete zone.',
      tripwire: 'Tripwire Mode: Click 1st endpoint, then click 2nd endpoint.',
      homography: 'Homography Mode: Click 4 floor corners in order: TL -> TR -> BR -> BL.',
    };
    updateStudioStatus(statusMap[mode] || '');
    drawStudioOverlay();
  }

  function updateStudioStatus(msg) {
    const banner = document.getElementById('studio-status-banner');
    if (banner) banner.textContent = msg;
  }

  // API Client Methods
  async function loadCameraScenario(cameraId) {
    try {
      const res = await fetch(`/api/scenarios/${encodeURIComponent(cameraId)}`);
      if (!res.ok) return;
      const data = await res.json();
      studioState.zones = data.zones || [];
      studioState.tripwires = data.tripwires || [];
      studioState.homography = data.homography || null;
      renderScenarioListUI();
      drawStudioOverlay();
      renderBEVMinimap();
    } catch (err) {
      console.warn('Failed to load scenario:', err);
    }
  }

  async function saveZone(zoneData) {
    try {
      const res = await fetch('/zones', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(zoneData),
      });
      if (res.ok) {
        showToast('Zone Saved', `Security zone '${zoneData.name}' created.`, 'success');
        loadCameraScenario(studioState.activeCamera);
      }
    } catch (err) {
      showToast('Zone Error', err.message, 'error');
    }
  }

  async function deleteZone(camera_id, zone_name) {
    if (!confirm(`Delete zone '${zone_name}'?`)) return;
    try {
      const res = await fetch(`/zones/${encodeURIComponent(zone_name)}?camera_id=${encodeURIComponent(camera_id)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showToast('Zone Deleted', `Zone '${zone_name}' removed.`, 'info');
        loadCameraScenario(studioState.activeCamera);
      }
    } catch (err) {
      showToast('Delete Error', err.message, 'error');
    }
  }

  async function saveTripwire(tripwireData) {
    try {
      const res = await fetch('/tripwires', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(tripwireData),
      });
      if (res.ok) {
        showToast('Tripwire Saved', `Tripwire '${tripwireData.name}' active.`, 'success');
        loadCameraScenario(studioState.activeCamera);
      }
    } catch (err) {
      showToast('Tripwire Error', err.message, 'error');
    }
  }

  async function deleteTripwire(camera_id, tripwire_name) {
    if (!confirm(`Delete tripwire '${tripwire_name}'?`)) return;
    try {
      const res = await fetch(`/tripwires/${encodeURIComponent(tripwire_name)}?camera_id=${encodeURIComponent(camera_id)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showToast('Tripwire Deleted', `Tripwire '${tripwire_name}' removed.`, 'info');
        loadCameraScenario(studioState.activeCamera);
      }
    } catch (err) {
      showToast('Delete Error', err.message, 'error');
    }
  }

  async function saveHomographyCalibration(data) {
    try {
      const res = await fetch('/api/homography/calibrate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (res.ok) {
        showToast('Calibration Saved', 'Ground plane homography matrix computed.', 'success');
        loadCameraScenario(studioState.activeCamera);
      }
    } catch (err) {
      showToast('Calibration Error', err.message, 'error');
    }
  }

  function renderBEVMinimap() {
    if (window.TrackerApp.BEVMinimap?.render) {
      window.TrackerApp.BEVMinimap.render(
        studioState.bevCanvas,
        studioState.bevCtx,
        studioState.activeCamera,
        studioState.homography,
        studioState.zones
      );
    }
  }

  // Floating Video Overlays Toolbar
  async function loadCameraOverlays(cameraId) {
    try {
      const res = await fetch(`/api/cameras/${encodeURIComponent(cameraId)}/overlays`);
      if (res.ok) {
        studioState.overlays = await res.json();
        updateOverlayCheckboxes();
      }
    } catch (err) {
      console.warn('Failed to load camera overlays:', err);
    }
  }

  async function updateOverlays(updates) {
    try {
      const res = await fetch(`/api/cameras/${encodeURIComponent(studioState.activeCamera)}/overlays`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (res.ok) {
        studioState.overlays = await res.json();
        updateOverlayCheckboxes();
      }
    } catch (err) {
      showToast('Overlay Error', err.message, 'error');
    }
  }

  function updateOverlayCheckboxes() {
    ['heatmaps', 'tripwires', 'zones', 'bboxes', 'bev_minimap'].forEach((key) => {
      const cb = document.getElementById(`cb-overlay-${key}`);
      if (cb) cb.checked = !!studioState.overlays[key];
    });
    const bevCard = document.getElementById('bev-minimap-card');
    if (bevCard) {
      bevCard.style.display = studioState.overlays.bev_minimap ? 'block' : 'none';
    }
  }

  function bindOverlayToolbar() {
    ['heatmaps', 'tripwires', 'zones', 'bboxes', 'bev_minimap'].forEach((key) => {
      const cb = document.getElementById(`cb-overlay-${key}`);
      if (cb) {
        cb.addEventListener('change', () => {
          const updates = {};
          updates[key] = cb.checked;
          updateOverlays(updates);
        });
      }
    });
  }

  function bindStudioUI() {
    document.getElementById('btn-tool-select')?.addEventListener('click', () => setStudioMode('idle'));
    document.getElementById('btn-tool-zone')?.addEventListener('click', () => setStudioMode('polygon'));
    document.getElementById('btn-tool-tripwire')?.addEventListener('click', () => setStudioMode('tripwire'));
    document.getElementById('btn-tool-homography')?.addEventListener('click', () => setStudioMode('homography'));
    document.getElementById('btn-studio-add-transition')?.addEventListener('click', openTransitionLinkModal);
  }

  function initStudioModals() {
    if (window.TrackerApp.ScenarioModals) {
      window.TrackerApp.ScenarioModals.init({
        saveZone: saveZone,
        saveTripwire: saveTripwire,
        saveHomography: saveHomographyCalibration,
        setMode: setStudioMode,
      });
    }
  }

  function openZoneModal(polygon) {
    window.TrackerApp.ScenarioModals?.openZoneModal(polygon);
  }

  function openTripwireModal(points) {
    window.TrackerApp.ScenarioModals?.openTripwireModal(points);
  }

  function openHomographyModal(points) {
    window.TrackerApp.ScenarioModals?.openHomographyModal(points);
  }

  function openTransitionLinkModal() {
    window.TrackerApp.ScenarioModals?.openTransitionLinkModal(studioState.activeCamera);
  }

  function renderScenarioListUI() {
    if (window.TrackerApp.ScenarioModals) {
      window.TrackerApp.ScenarioModals.renderScenarioListUI(
        studioState.zones,
        studioState.tripwires,
        studioState.activeCamera,
        deleteZone,
        deleteTripwire
      );
    }
  }

  // Periodic loop for BEV Minimap agent position updates
  setInterval(() => {
    if (document.getElementById('tab-studio')?.classList.contains('active') ||
        studioState.overlays.bev_minimap) {
      renderBEVMinimap();
    }
  }, 250);

  // Expose global Studio API
  window.Studio = {
    init: initStudio,
    setMode: setStudioMode,
    deleteZone: deleteZone,
    deleteTripwire: deleteTripwire,
    deleteTopologyLink: (linkId) => window.TrackerApp.Topology?.deleteLink(linkId),
    renderBEV: renderBEVMinimap,
    searchJourney: (q) => window.TrackerApp.Topology?.searchJourney(q),
    exportJourney: (q) => window.TrackerApp.Topology?.exportJourney(q),
  };

  document.addEventListener('DOMContentLoaded', initStudio);
})();
