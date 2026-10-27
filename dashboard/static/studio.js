/**
 * Intelligent Tracker - World Scenario Studio, Space Awareness & Homography Controller
 * Milestone 8 Implementation
 */

(function () {
  'use strict';

  // State Management
  const studioState = {
    activeCamera: 'cam_01',
    mode: 'idle', // 'idle', 'draw_zone', 'draw_tripwire', 'calibrate_homography'
    points: [],
    zones: [],
    tripwires: [],
    homography: null,
    topologyLinks: [],
    activePriors: [],
    overlays: {
      bboxes: true,
      track_ids: true,
      dwell_timers: true,
      velocity: true,
      zones: true,
      tripwires: true,
      heatmap: false,
      bev_minimap: false,
      hud_bar: true,
      toast_prompts: true,
    },
    canvas: null,
    ctx: null,
    bevCanvas: null,
    bevCtx: null,
  };

  // ---------------------------------------------------------------------------
  // Initialization
  // ---------------------------------------------------------------------------
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

    // Attach button event listeners
    bindStudioUI();
    bindOverlayToolbar();
    bindJourneySearch();

    // Load initial data
    loadCameraScenario(studioState.activeCamera);
    loadTopologyLinks();
    loadCameraOverlays(studioState.activeCamera);
  }

  // ---------------------------------------------------------------------------
  // Canvas Event Handling (Drawing & Calibration)
  // ---------------------------------------------------------------------------
  function setupCanvasEventListeners(canvas) {
    canvas.addEventListener('click', onCanvasClick);
    canvas.addEventListener('mousemove', onCanvasMouseMove);
    canvas.addEventListener('dblclick', onCanvasDblClick);
  }

  function getCanvasCoords(evt, canvas) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: Math.round((evt.clientX - rect.left) * scaleX),
      y: Math.round((evt.clientY - rect.top) * scaleY),
    };
  }

  function onCanvasClick(evt) {
    if (studioState.mode === 'idle') return;

    const pt = getCanvasCoords(evt, studioState.canvas);

    if (studioState.mode === 'draw_zone') {
      studioState.points.push([pt.x, pt.y]);
      drawStudioOverlay();
      updateStudioStatus(`Zone vertex #${studioState.points.length} placed at (${pt.x}, ${pt.y}). Double-click to close polygon.`);
    } else if (studioState.mode === 'draw_tripwire') {
      studioState.points.push([pt.x, pt.y]);
      drawStudioOverlay();
      if (studioState.points.length === 2) {
        openTripwireModal(studioState.points);
      } else {
        updateStudioStatus(`Tripwire start point set at (${pt.x}, ${pt.y}). Click end point.`);
      }
    } else if (studioState.mode === 'calibrate_homography') {
      if (studioState.points.length < 4) {
        studioState.points.push([pt.x, pt.y]);
        drawStudioOverlay();
        const cornerNames = ['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left'];
        const nextIdx = studioState.points.length;
        if (nextIdx < 4) {
          updateStudioStatus(`Corner ${nextIdx}/4 placed (${cornerNames[nextIdx - 1]}). Click corner #${nextIdx + 1} (${cornerNames[nextIdx]}).`);
        } else {
          updateStudioStatus(`All 4 ground corners selected! Enter metric dimensions and click Save Calibration.`);
          openHomographyModal(studioState.points);
        }
      }
    }
  }

  function onCanvasMouseMove(evt) {
    if (studioState.mode === 'idle' || studioState.points.length === 0) return;
    const pt = getCanvasCoords(evt, studioState.canvas);
    drawStudioOverlay(pt);
  }

  function onCanvasDblClick(evt) {
    if (studioState.mode === 'draw_zone') {
      if (studioState.points.length >= 3) {
        openZoneModal(studioState.points);
      } else {
        alert('A polygonal zone requires at least 3 vertices.');
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Canvas Rendering (Drawing Preview)
  // ---------------------------------------------------------------------------
  function drawStudioOverlay(cursorPt) {
    const ctx = studioState.ctx;
    if (!ctx || !studioState.canvas) return;

    ctx.clearRect(0, 0, studioState.canvas.width, studioState.canvas.height);

    const pts = studioState.points;
    if (pts.length === 0) return;

    ctx.save();

    if (studioState.mode === 'draw_zone') {
      // Draw polygon edges
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) {
        ctx.lineTo(pts[i][0], pts[i][1]);
      }
      if (cursorPt) {
        ctx.lineTo(cursorPt.x, cursorPt.y);
      }
      ctx.closePath();
      ctx.fillStyle = 'rgba(0, 200, 100, 0.25)';
      ctx.fill();
      ctx.strokeStyle = '#00ff88';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Draw vertices
      for (let i = 0; i < pts.length; i++) {
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(pts[i][0], pts[i][1], 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#00ff88';
        ctx.stroke();
      }
    } else if (studioState.mode === 'draw_tripwire') {
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      const endX = cursorPt ? cursorPt.x : (pts[1] ? pts[1][0] : pts[0][0]);
      const endY = cursorPt ? cursorPt.y : (pts[1] ? pts[1][1] : pts[0][1]);
      ctx.lineTo(endX, endY);
      ctx.strokeStyle = '#facc15';
      ctx.lineWidth = 3;
      ctx.stroke();

      // Normal vector arrow (direction)
      const dx = endX - pts[0][0];
      const dy = endY - pts[0][1];
      const len = Math.hypot(dx, dy);
      if (len > 20) {
        const midX = (pts[0][0] + endX) / 2;
        const midY = (pts[0][1] + endY) / 2;
        const nx = -dy / len;
        const ny = dx / len;
        ctx.beginPath();
        ctx.moveTo(midX, midY);
        ctx.lineTo(midX + nx * 25, midY + ny * 25);
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Arrow head
        ctx.fillStyle = '#38bdf8';
        ctx.beginPath();
        ctx.arc(midX + nx * 25, midY + ny * 25, 4, 0, Math.PI * 2);
        ctx.fill();
      }
    } else if (studioState.mode === 'calibrate_homography') {
      // Draw quadrilateral
      if (pts.length > 1) {
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) {
          ctx.lineTo(pts[i][0], pts[i][1]);
        }
        if (pts.length === 4) {
          ctx.closePath();
          ctx.fillStyle = 'rgba(14, 165, 233, 0.2)';
          ctx.fill();
        }
        ctx.strokeStyle = '#0ea5e9';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Draw labeled corner circles
      const cornerNames = ['1: TL', '2: TR', '3: BR', '4: BL'];
      for (let i = 0; i < pts.length; i++) {
        ctx.fillStyle = '#0ea5e9';
        ctx.beginPath();
        ctx.arc(pts[i][0], pts[i][1], 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 12px Inter, sans-serif';
        ctx.fillText(cornerNames[i] || `${i + 1}`, pts[i][0] + 8, pts[i][1] - 8);
      }
    }

    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // REST API Integrations: Scenarios, Zones, Tripwires & Homography
  // ---------------------------------------------------------------------------
  async function loadCameraScenario(cameraId) {
    try {
      const res = await fetch(`/api/scenarios/${cameraId}`);
      if (!res.ok) return;
      const data = await res.json();
      studioState.zones = data.zones || [];
      studioState.tripwires = data.tripwires || [];
      studioState.homography = data.homography || null;

      renderScenarioListUI();
      renderBEVMinimap();
    } catch (err) {
      console.warn('Failed to load scenario:', err);
    }
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
        loadCameraScenario(zoneData.camera_id);
      }
    } catch (err) {
      alert(`Error saving zone: ${err.message}`);
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
        loadCameraScenario(camera_id);
      }
    } catch (err) {
      alert(`Error deleting zone: ${err.message}`);
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
        loadCameraScenario(tripwireData.camera_id);
      }
    } catch (err) {
      alert(`Error saving tripwire: ${err.message}`);
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
        loadCameraScenario(camera_id);
      }
    } catch (err) {
      alert(`Error deleting tripwire: ${err.message}`);
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
        renderBEVMinimap();
      }
    } catch (err) {
      alert(`Error calibrating homography: ${err.message}`);
    }
  }

  // ---------------------------------------------------------------------------
  // Cross-Camera Topology Links
  // ---------------------------------------------------------------------------
  async function loadTopologyLinks() {
    try {
      const res = await fetch('/api/topology/transitions');
      if (!res.ok) return;
      studioState.topologyLinks = await res.json();
      renderTopologyLinksUI();
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
        updateStudioStatus(`Transition link '${linkData.source_camera}[${linkData.source_zone}] -> ${linkData.target_camera}[${linkData.target_zone}]' active.`);
        loadTopologyLinks();
      }
    } catch (err) {
      alert(`Error creating spatial transition: ${err.message}`);
    }
  }

  async function deleteTopologyLink(linkId) {
    if (!confirm(`Remove transition link '${linkId}'?`)) return;
    try {
      const res = await fetch(`/api/topology/transitions/${encodeURIComponent(linkId)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        loadTopologyLinks();
      }
    } catch (err) {
      alert(`Error removing transition link: ${err.message}`);
    }
  }

  // ---------------------------------------------------------------------------
  // Top-Down Bird's-Eye-View (BEV) Minimap Rendering
  // ---------------------------------------------------------------------------
  function renderBEVMinimap() {
    const canvas = studioState.bevCanvas;
    const ctx = studioState.bevCtx;
    if (!canvas || !ctx) return;

    const cw = canvas.width;
    const ch = canvas.height;
    ctx.clearRect(0, 0, cw, ch);

    // Dark tactical background
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, cw, ch);

    const margin = 35;
    const innerW = cw - 2 * margin;
    const innerH = ch - 2 * margin;

    const homo = studioState.homography;
    const gw = (homo && homo.metric_width) ? homo.metric_width : 10.0;
    const gh = (homo && homo.metric_height) ? homo.metric_height : 10.0;

    const scaleX = innerW / gw;
    const scaleY = innerH / gh;

    function g2c(gx, gy) {
      return {
        x: Math.round(margin + gx * scaleX),
        y: Math.round(margin + gy * scaleY),
      };
    }

    // Grid boundary
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 1;
    ctx.strokeRect(margin, margin, innerW, innerH);

    // Metric Grid Lines
    ctx.fillStyle = '#64748b';
    ctx.font = '10px JetBrains Mono, monospace';

    const stepX = Math.max(2, Math.floor(gw / 4));
    for (let gx = stepX; gx < gw; gx += stepX) {
      const p1 = g2c(gx, 0);
      const p2 = g2c(gx, gh);
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.strokeStyle = '#1e293b';
      ctx.stroke();
      ctx.fillText(`${gx}m`, p1.x - 8, ch - margin + 14);
    }

    const stepY = Math.max(2, Math.floor(gh / 4));
    for (let gy = stepY; gy < gh; gy += stepY) {
      const p1 = g2c(0, gy);
      const p2 = g2c(gw, gy);
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.strokeStyle = '#1e293b';
      ctx.stroke();
      ctx.fillText(`${gy}m`, 6, p1.y + 3);
    }

    // Title Badge
    ctx.fillStyle = '#00e5ff';
    ctx.font = 'bold 11px Inter, sans-serif';
    ctx.fillText(`BEV: ${studioState.activeCamera} (${gw}m x ${gh}m)`, margin, 20);

    // Draw Transformed Zones
    if (studioState.zones) {
      studioState.zones.forEach((z) => {
        if (!z.polygon || z.polygon.length < 3) return;
        ctx.beginPath();
        const p0 = g2c((z.polygon[0][0] / 640) * gw, (z.polygon[0][1] / 480) * gh);
        ctx.moveTo(p0.x, p0.y);
        for (let i = 1; i < z.polygon.length; i++) {
          const pt = g2c((z.polygon[i][0] / 640) * gw, (z.polygon[i][1] / 480) * gh);
          ctx.lineTo(pt.x, pt.y);
        }
        ctx.closePath();
        ctx.fillStyle = 'rgba(0, 200, 100, 0.2)';
        ctx.fill();
        ctx.strokeStyle = '#00ff88';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        ctx.fillStyle = '#ffffff';
        ctx.font = '10px Inter, sans-serif';
        ctx.fillText(z.name, p0.x + 4, p0.y + 12);
      });
    }

    // Draw Simulated or Telemetry Agents
    if (window.latestTelemetry && window.latestTelemetry.active_tracks) {
      window.latestTelemetry.active_tracks.forEach((trk) => {
        let gx = (trk.bbox[0] + trk.bbox[2] / 2) / 640 * gw;
        let gy = (trk.bbox[1] + trk.bbox[3]) / 480 * gh;
        if (trk.ground_pos) {
          gx = trk.ground_pos[0];
          gy = trk.ground_pos[1];
        }

        const cp = g2c(gx, gy);
        ctx.beginPath();
        ctx.arc(cp.x, cp.y, 6, 0, Math.PI * 2);
        ctx.fillStyle = trk.category === 'restricted' ? '#ef4444' : '#22c55e';
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1;
        ctx.stroke();

        ctx.fillStyle = '#f8fafc';
        ctx.font = 'bold 9px Inter, sans-serif';
        ctx.fillText(trk.entity_name || `#${trk.id}`, cp.x + 8, cp.y + 3);
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Floating Video Overlays Toolbar
  // ---------------------------------------------------------------------------
  async function loadCameraOverlays(cameraId) {
    try {
      const res = await fetch(`/api/cameras/${cameraId}/overlays`);
      if (res.ok) {
        const data = await res.json();
        Object.assign(studioState.overlays, data);
        updateOverlayCheckboxes();
      }
    } catch (err) {
      console.warn('Failed loading overlays:', err);
    }
  }

  async function updateOverlays(updates) {
    Object.assign(studioState.overlays, updates);
    updateOverlayCheckboxes();

    try {
      await fetch(`/api/cameras/${studioState.activeCamera}/overlays`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
    } catch (err) {
      console.warn('Error saving overlays:', err);
    }
  }

  function updateOverlayCheckboxes() {
    Object.keys(studioState.overlays).forEach((key) => {
      const el = document.getElementById(`overlay-toggle-${key}`);
      if (el) {
        el.checked = !!studioState.overlays[key];
      }
    });
  }

  function bindOverlayToolbar() {
    const keys = [
      'bboxes', 'track_ids', 'dwell_timers', 'velocity',
      'zones', 'tripwires', 'heatmap', 'bev_minimap', 'hud_bar', 'toast_prompts'
    ];

    keys.forEach((key) => {
      const el = document.getElementById(`overlay-toggle-${key}`);
      if (el) {
        el.addEventListener('change', (e) => {
          updateOverlays({ [key]: e.target.checked });
        });
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Trajectory Journey Search & Video Exporter
  // ---------------------------------------------------------------------------
  function bindJourneySearch() {
    const btnSearch = document.getElementById('btn-journey-search');
    const btnExport = document.getElementById('btn-journey-export');

    if (btnSearch) {
      btnSearch.addEventListener('click', () => {
        const query = document.getElementById('journey-search-query').value.trim();
        searchJourney(query);
      });
    }

    if (btnExport) {
      btnExport.addEventListener('click', () => {
        const query = document.getElementById('journey-search-query').value.trim();
        exportJourneyVideo(query);
      });
    }
  }

  async function searchJourney(entityNameOrId) {
    const container = document.getElementById('journey-results-container');
    if (!container) return;

    container.innerHTML = '<div class="loading-state">🔍 Reconstructing cross-camera trajectory journey...</div>';

    try {
      const param = isNaN(entityNameOrId) ? `entity_name=${encodeURIComponent(entityNameOrId)}` : `entity_id=${entityNameOrId}`;
      const res = await fetch(`/api/journey/search?${param}`);
      if (!res.ok) {
        container.innerHTML = '<div class="empty-state">No journey sightings found for this entity.</div>';
        return;
      }

      const journey = await res.json();
      renderJourneyResults(journey);
    } catch (err) {
      container.innerHTML = `<div class="error-state">Error searching journey: ${err.message}</div>`;
    }
  }

  function renderJourneyResults(journey) {
    const container = document.getElementById('journey-results-container');
    if (!container) return;

    if (!journey.hops || journey.hops.length === 0) {
      container.innerHTML = '<div class="empty-state">No camera transitions detected for this entity.</div>';
      return;
    }

    let html = `
      <div class="journey-summary-card glass-panel">
        <div class="journey-header">
          <h4>🚶 Trajectory Journey: <strong>${journey.entity_name}</strong> (${journey.category.toUpperCase()})</h4>
          <span class="badge ${journey.total_hops > 1 ? 'badge-primary' : 'badge-secondary'}">${journey.total_hops} Hops | ${journey.total_duration_seconds}s</span>
        </div>
        <div class="journey-narrative">${journey.summary_narrative}</div>
      </div>
      <div class="journey-hops-timeline">
    `;

    journey.hops.forEach((hop, idx) => {
      const startTimeStr = new Date(hop.start_time * 1000).toLocaleTimeString();
      const transitBadge = hop.transit_time_from_prev
        ? `<div class="transit-connector"><span>⏱️ Transit: +${hop.transit_time_from_prev}s</span></div>`
        : '';

      const thumbUrl = hop.snapshot_path ? `/crops/${hop.snapshot_path.split(/[\\/]/).pop()}` : '';

      html += `
        ${transitBadge}
        <div class="hop-card glass-panel">
          <div class="hop-num">#${hop.hop_index}</div>
          <div class="hop-details">
            <div class="hop-title">
              <strong>${hop.camera_name}</strong>
              <span class="hop-time">${startTimeStr}</span>
            </div>
            <div class="hop-meta">
              <span>Zone: ${hop.zone_id || 'General Area'}</span> •
              <span>Dwell: ${hop.duration_seconds}s</span> •
              <span>Sightings: ${hop.sightings_count}</span>
            </div>
          </div>
          ${thumbUrl ? `<div class="hop-thumb"><img src="${thumbUrl}" alt="Snapshot" /></div>` : ''}
        </div>
      `;
    });

    html += '</div>';
    container.innerHTML = html;
  }

  async function exportJourneyVideo(entityNameOrId) {
    const btn = document.getElementById('btn-journey-export');
    const statusDiv = document.getElementById('journey-export-status');
    if (btn) btn.disabled = true;
    if (statusDiv) statusDiv.innerHTML = '⏳ Slicing footage and concatenating MP4 video with tactical HUD title cards...';

    try {
      const payload = isNaN(entityNameOrId) ? { entity_name: entityNameOrId } : { entity_id: parseInt(entityNameOrId, 10) };
      const res = await fetch('/api/journey/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Export failed');
      }

      const data = await res.json();
      if (statusDiv) {
        statusDiv.innerHTML = `
          <div class="alert alert-success">
            ✅ <strong>Journey MP4 Ready!</strong>
            <a href="${data.video_url}" target="_blank" class="btn btn-sm btn-primary" download>⬇️ Download MP4 (${data.video_file})</a>
            <div class="video-preview-box" style="margin-top: 10px;">
              <video src="${data.video_url}" controls autoplay style="max-width: 100%; border-radius: 6px;"></video>
            </div>
          </div>
        `;
      }
    } catch (err) {
      if (statusDiv) statusDiv.innerHTML = `<div class="alert alert-danger">❌ Export failed: ${err.message}</div>`;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Modals & UI Binding
  // ---------------------------------------------------------------------------
  function bindStudioUI() {
    const btnModeZone = document.getElementById('btn-mode-draw-zone');
    const btnModeTw = document.getElementById('btn-mode-draw-tripwire');
    const btnModeHomo = document.getElementById('btn-mode-homography');
    const btnClearCanvas = document.getElementById('btn-studio-clear');

    if (btnModeZone) {
      btnModeZone.addEventListener('click', () => setStudioMode('draw_zone'));
    }
    if (btnModeTw) {
      btnModeTw.addEventListener('click', () => setStudioMode('draw_tripwire'));
    }
    if (btnModeHomo) {
      btnModeHomo.addEventListener('click', () => setStudioMode('calibrate_homography'));
    }
    if (btnClearCanvas) {
      btnClearCanvas.addEventListener('click', () => {
        setStudioMode('idle');
        studioState.points = [];
        drawStudioOverlay();
        updateStudioStatus('Canvas cleared. Mode: Idle.');
      });
    }

    // Add Transition Link Modal button
    const btnAddLink = document.getElementById('btn-add-transition-link');
    if (btnAddLink) {
      btnAddLink.addEventListener('click', openTransitionLinkModal);
    }
  }

  function setStudioMode(mode) {
    studioState.mode = mode;
    studioState.points = [];
    drawStudioOverlay();

    document.querySelectorAll('.studio-tool-btn').forEach((b) => b.classList.remove('active'));
    if (mode === 'draw_zone') document.getElementById('btn-mode-draw-zone')?.classList.add('active');
    if (mode === 'draw_tripwire') document.getElementById('btn-mode-draw-tripwire')?.classList.add('active');
    if (mode === 'calibrate_homography') document.getElementById('btn-mode-homography')?.classList.add('active');

    const descriptions = {
      idle: 'Click a tool to draw zones, tripwires or calibrate BEV.',
      draw_zone: 'Click directly on video to place polygon vertices. Double click to finish.',
      draw_tripwire: 'Click start point and end point to draw directional tripwire.',
      calibrate_homography: 'Click 4 ground plane corners: (1) Top-Left, (2) Top-Right, (3) Bottom-Right, (4) Bottom-Left.',
    };
    updateStudioStatus(descriptions[mode] || '');
  }

  function updateStudioStatus(text) {
    const el = document.getElementById('studio-status-banner');
    if (el) el.textContent = text;
  }

  function openZoneModal(polygon) {
    const name = prompt('Enter Zone Name (e.g., Vault Perimeter, Door Exit):', `zone_${Date.now() % 1000}`);
    if (!name) {
      setStudioMode('idle');
      return;
    }
    const cat = prompt('Category Filter (leave blank for all, or restricted, staff, vip):', '');
    const dwell = parseFloat(prompt('Dwell Threshold in seconds (default: 5.0):', '5.0')) || 5.0;
    const capacity = parseInt(prompt('Max Capacity limit (optional, 0 for none):', '0'), 10) || null;

    saveZone({
      camera_id: studioState.activeCamera,
      name: name.trim(),
      polygon: polygon,
      category_filter: (cat || '').trim(),
      dwell_threshold: dwell,
      capacity_limit: capacity,
      color: [0, 200, 100],
    });

    setStudioMode('idle');
  }

  function openTripwireModal(points) {
    const name = prompt('Enter Tripwire Name (e.g., Entrance Line, Hallway A):', `tw_${Date.now() % 1000}`);
    if (!name) {
      setStudioMode('idle');
      return;
    }
    const bidir = confirm('Is crossing detection bidirectional (IN & OUT)? OK=Yes, Cancel=One-way');

    saveTripwire({
      camera_id: studioState.activeCamera,
      name: name.trim(),
      line_segment: points,
      bidirectional: bidir,
      color: [0, 255, 255],
    });

    setStudioMode('idle');
  }

  function openHomographyModal(points) {
    const w = parseFloat(prompt('Enter real-world ground plane WIDTH in meters:', '10.0')) || 10.0;
    const h = parseFloat(prompt('Enter real-world ground plane HEIGHT in meters:', '10.0')) || 10.0;

    saveHomographyCalibration({
      camera_id: studioState.activeCamera,
      src_points: points,
      metric_width: w,
      metric_height: h,
    });

    setStudioMode('idle');
  }

  function openTransitionLinkModal() {
    const srcCam = prompt('Source Camera ID (e.g. cam_01):', studioState.activeCamera);
    if (!srcCam) return;
    const srcZone = prompt('Source Zone Name (e.g. Door Exit):', 'Door Exit');
    if (!srcZone) return;
    const tgtCam = prompt('Target Camera ID (e.g. cam_02):', 'cam_02');
    if (!tgtCam) return;
    const tgtZone = prompt('Target Zone Name (e.g. Door Entrance):', 'Door Entrance');
    if (!tgtZone) return;
    const tMin = parseFloat(prompt('Minimum transit time (seconds, e.g. 2.0):', '2.0')) || 2.0;
    const tMax = parseFloat(prompt('Maximum transit time (seconds, e.g. 15.0):', '15.0')) || 15.0;
    const boost = parseFloat(prompt('Spatial Prior score bonus (0.1 to 0.5, e.g. 0.35):', '0.35')) || 0.35;
    const bidir = confirm('Make transition bidirectional?');

    saveTopologyLink({
      source_camera: srcCam.trim(),
      source_zone: srcZone.trim(),
      target_camera: tgtCam.trim(),
      target_zone: tgtZone.trim(),
      t_min: tMin,
      t_max: tMax,
      prior_boost: boost,
      bidirectional: bidir,
    });
  }

  function renderScenarioListUI() {
    const zoneListEl = document.getElementById('studio-zones-list');
    if (zoneListEl) {
      if (studioState.zones.length === 0) {
        zoneListEl.innerHTML = '<div class="empty-state">No zones defined. Click Draw Zone to create one.</div>';
      } else {
        zoneListEl.innerHTML = studioState.zones.map((z) => `
          <div class="studio-item-card">
            <div class="item-title">
              <span class="color-dot" style="background: rgb(${z.color[2]}, ${z.color[1]}, ${z.color[0]});"></span>
              <strong>${z.name}</strong>
              ${z.capacity_limit ? `<span class="badge">Cap: ${z.capacity_limit}</span>` : ''}
            </div>
            <div class="item-sub">${z.polygon.length} vertices | Dwell: ${z.dwell_threshold}s</div>
            <button class="btn btn-xs btn-outline-danger" onclick="window.Studio.deleteZone('${studioState.activeCamera}', '${z.name}')">🗑️</button>
          </div>
        `).join('');
      }
    }

    const twListEl = document.getElementById('studio-tripwires-list');
    if (twListEl) {
      if (studioState.tripwires.length === 0) {
        twListEl.innerHTML = '<div class="empty-state">No tripwires defined. Click Draw Tripwire.</div>';
      } else {
        twListEl.innerHTML = studioState.tripwires.map((tw) => `
          <div class="studio-item-card">
            <div class="item-title">
              <span class="color-dot" style="background: rgb(${tw.color[2]}, ${tw.color[1]}, ${tw.color[0]});"></span>
              <strong>${tw.name}</strong>
              <span class="badge">${tw.bidirectional ? 'IN/OUT' : 'One-Way'}</span>
            </div>
            <div class="item-sub">(${tw.line_segment[0][0]}, ${tw.line_segment[0][1]}) -> (${tw.line_segment[1][0]}, ${tw.line_segment[1][1]})</div>
            <button class="btn btn-xs btn-outline-danger" onclick="window.Studio.deleteTripwire('${studioState.activeCamera}', '${tw.name}')">🗑️</button>
          </div>
        `).join('');
      }
    }
  }

  function renderTopologyLinksUI() {
    const listEl = document.getElementById('topology-links-list');
    if (!listEl) return;

    if (studioState.topologyLinks.length === 0) {
      listEl.innerHTML = '<div class="empty-state">No transition links registered. Click + Add Spatial Transition.</div>';
      return;
    }

    listEl.innerHTML = studioState.topologyLinks.map((l) => `
      <div class="topology-link-card glass-panel">
        <div class="link-flow">
          <span class="cam-badge">${l.source_camera}</span>
          <span class="zone-badge">${l.source_zone}</span>
          <span class="arrow">${l.bidirectional ? '⟷' : '⟶'}</span>
          <span class="cam-badge">${l.target_camera}</span>
          <span class="zone-badge">${l.target_zone}</span>
        </div>
        <div class="link-timing">
          <span>Transit Window: <strong>${l.t_min}s – ${l.t_max}s</strong></span> •
          <span>Prior Boost: <strong>+${(l.prior_boost * 100).toFixed(0)}%</strong></span>
        </div>
        <button class="btn btn-xs btn-outline-danger" onclick="window.Studio.deleteTopologyLink('${l.link_id}')">🗑️ Remove</button>
      </div>
    `).join('');
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
    deleteTopologyLink: deleteTopologyLink,
    renderBEV: renderBEVMinimap,
    searchJourney: searchJourney,
    exportJourney: exportJourneyVideo,
  };

  document.addEventListener('DOMContentLoaded', initStudio);
})();
