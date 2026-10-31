/**
 * Intelligent Tracker - Studio Overlays & Scenario UI Submodule.
 * Manages overlay checkboxes, camera overlay settings persistence,
 * and rendering lists for zones, tripwires, and topology transitions.
 */

(function () {
  'use strict';

  let _getState = () => ({});

  function init(getState) {
    _getState = getState;
  }

  async function loadCameraOverlays(cameraId) {
    const state = _getState();
    try {
      const res = await fetch(`/api/cameras/${cameraId}/overlays`);
      if (res.ok) {
        const data = await res.json();
        Object.assign(state.overlays, data);
        updateOverlayCheckboxes();
      }
    } catch (err) {
      console.warn('Failed loading overlays:', err);
    }
  }

  async function updateOverlays(updates) {
    const state = _getState();
    Object.assign(state.overlays, updates);
    updateOverlayCheckboxes();
    try {
      await fetch(`/api/cameras/${state.activeCamera}/overlays`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
    } catch (err) {
      console.warn('Error saving overlays:', err);
    }
  }

  function updateOverlayCheckboxes() {
    const state = _getState();
    Object.keys(state.overlays).forEach((key) => {
      const el = document.getElementById(`overlay-toggle-${key}`);
      if (el) el.checked = !!state.overlays[key];
    });
  }

  function bindOverlayToolbar() {
    const keys = [
      'bboxes', 'track_ids', 'dwell_timers', 'velocity',
      'zones', 'tripwires', 'heatmap', 'bev_minimap', 'hud_bar', 'toast_prompts'
    ];
    keys.forEach((key) => {
      document.getElementById(`overlay-toggle-${key}`)?.addEventListener('change', (e) => {
        updateOverlays({ [key]: e.target.checked });
      });
    });
  }

  function renderScenarioListUI() {
    const state = _getState();
    const zoneListEl = document.getElementById('studio-zones-list');
    if (zoneListEl) {
      zoneListEl.innerHTML = state.zones.length === 0
        ? '<div class="empty-state">No zones defined. Click Draw Zone to create one.</div>'
        : state.zones.map((z) => `
          <div class="studio-item-card">
            <div class="item-title">
              <span class="color-dot" style="background: rgb(${z.color[2]}, ${z.color[1]}, ${z.color[0]});"></span>
              <strong>${z.name}</strong>
              ${z.capacity_limit ? `<span class="badge">Cap: ${z.capacity_limit}</span>` : ''}
            </div>
            <div class="item-sub">${z.polygon.length} vertices | Dwell: ${z.dwell_threshold}s</div>
            <button class="btn btn-xs btn-outline-danger" onclick="window.Studio.deleteZone('${state.activeCamera}', '${z.name}')">🗑️</button>
          </div>
        `).join('');
    }

    const twListEl = document.getElementById('studio-tripwires-list');
    if (twListEl) {
      twListEl.innerHTML = state.tripwires.length === 0
        ? '<div class="empty-state">No tripwires defined. Click Draw Tripwire.</div>'
        : state.tripwires.map((tw) => `
          <div class="studio-item-card">
            <div class="item-title">
              <span class="color-dot" style="background: rgb(${tw.color[2]}, ${tw.color[1]}, ${tw.color[0]});"></span>
              <strong>${tw.name}</strong>
              <span class="badge">${tw.bidirectional ? 'IN/OUT' : 'One-Way'}</span>
            </div>
            <div class="item-sub">(${tw.line_segment[0][0]}, ${tw.line_segment[0][1]}) -> (${tw.line_segment[1][0]}, ${tw.line_segment[1][1]})</div>
            <button class="btn btn-xs btn-outline-danger" onclick="window.Studio.deleteTripwire('${state.activeCamera}', '${tw.name}')">🗑️</button>
          </div>
        `).join('');
    }
  }

  function renderTopologyLinksUI() {
    const state = _getState();
    const listEl = document.getElementById('topology-links-list');
    if (!listEl) return;

    listEl.innerHTML = state.topologyLinks.length === 0
      ? '<div class="empty-state">No transition links registered. Click + Add Spatial Transition.</div>'
      : state.topologyLinks.map((l) => `
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

  window.StudioOverlays = {
    init: init,
    loadCameraOverlays: loadCameraOverlays,
    updateOverlays: updateOverlays,
    updateOverlayCheckboxes: updateOverlayCheckboxes,
    bindOverlayToolbar: bindOverlayToolbar,
    renderScenarioListUI: renderScenarioListUI,
    renderTopologyLinksUI: renderTopologyLinksUI,
  };
})();

