/**
 * Intelligent Tracker - Studio Overlays & Scenario UI Submodule.
 * Manages overlay checkboxes, camera overlay settings persistence,
 * and rendering lists for zones, tripwires, and topology transitions.
 */

(function () {
  'use strict';

  let _getState = () => ({});
  let _delegatedListsBound = false;

  const VALID_OVERLAY_KEYS = [
    'bboxes', 'track_ids', 'dwell_timers', 'velocity',
    'zones', 'tripwires', 'heatmap', 'bev_minimap', 'hud_bar', 'clutter',
  ];

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function resolveLiveTargetCamera() {
    const state = _getState();
    return window.App?.getActiveCameraId?.()
      || document.getElementById('active-camera-select')?.value
      || state.activeCamera
      || null;
  }

  function syncLiveBevPip(enabled) {
    const pip = document.getElementById('live-bev-pip-canvas');
    if (!pip) return;
    pip.hidden = !enabled;
    if (enabled) {
      const state = _getState();
      const camId = resolveLiveTargetCamera();
      window.BEVMinimap?.render(pip, state.homography, state.zones, camId);
    }
  }

  function init(getState) {
    _getState = getState;
  }

  async function loadCameraOverlays(cameraId) {
    if (!cameraId) return;
    const state = _getState();
    try {
      const res = await fetch(`/api/cameras/${encodeURIComponent(cameraId)}/overlays`);
      if (res.ok) {
        const data = await res.json();
        state.overlays = state.overlays || {};
        Object.assign(state.overlays, data);
        updateOverlayCheckboxes();
      }
    } catch (err) {
      console.warn('Failed loading overlays:', err);
    }
  }

  async function updateOverlays(updates) {
    const state = _getState();
    state.overlays = state.overlays || {};
    Object.assign(state.overlays, updates);
    updateOverlayCheckboxes();
    const targetCam = resolveLiveTargetCamera();
    if (!targetCam) return;
    try {
      await fetch(`/api/cameras/${encodeURIComponent(targetCam)}/overlays`, {
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
    const overlays = state.overlays || {};
    Object.keys(overlays).forEach((key) => {
      const el = document.getElementById(`overlay-toggle-${key}`);
      if (el) el.checked = !!overlays[key];
    });
    syncLiveBevPip(Boolean(overlays.bev_minimap));
  }

  function bindOverlayToolbar() {
    const state = _getState();
    const container = document.getElementById('live-overlay-control-bar');
    if (container && window.OverlayControlBar?.mount) {
      window.OverlayControlBar.mount({
        container,
        variant: 'live',
        values: state.overlays || {},
        onToggle: (key, checked) => updateOverlays({ [key]: checked }),
      });
    } else {
      VALID_OVERLAY_KEYS.forEach((key) => {
        document.getElementById(`overlay-toggle-${key}`)?.addEventListener('change', (e) => {
          updateOverlays({ [key]: e.target.checked });
        });
      });
    }
    document.getElementById('active-camera-select')?.addEventListener('change', (e) => {
      if (e.target?.value) loadCameraOverlays(e.target.value);
    });
  }

  function bindDelegatedScenarioActions() {
    if (_delegatedListsBound) return;
    _delegatedListsBound = true;
    const handleListClick = (e) => {
      const btn = e.target?.closest?.('button[data-action]');
      if (!btn) return;
      const { action, cameraId, name, linkId } = btn.dataset;
      if (action === 'delete-zone') window.Studio?.deleteZone(cameraId, name);
      else if (action === 'rename-zone') window.StudioShapeEditor?.renameShape?.('zone', cameraId, name);
      else if (action === 'delete-tripwire') window.Studio?.deleteTripwire(cameraId, name);
      else if (action === 'rename-tripwire') window.StudioShapeEditor?.renameShape?.('tripwire', cameraId, name);
      else if (action === 'delete-topology-link') window.Studio?.deleteTopologyLink(linkId);
    };
    ['studio-zones-list', 'studio-tripwires-list', 'topology-links-list'].forEach((id) => {
      document.getElementById(id)?.addEventListener('click', handleListClick);
    });
  }

  function renderScenarioListUI() {
    bindDelegatedScenarioActions();
    const state = _getState();
    const zoneListEl = document.getElementById('studio-zones-list');
    if (zoneListEl) {
      zoneListEl.innerHTML = state.zones.length === 0
        ? '<div class="empty-state">No zones defined. Click Draw Zone to create one.</div>'
        : state.zones.map((z) => `
          <div class="studio-item-card">
            <div class="item-title">
              <span class="color-dot" style="background: rgb(${z.color[2]}, ${z.color[1]}, ${z.color[0]});"></span>
              <strong>${escapeHtml(z.name)}</strong>
              ${z.capacity_limit ? `<span class="badge">Cap: ${z.capacity_limit}</span>` : ''}
            </div>
            <div class="item-sub">${z.polygon.length} vertices | Dwell: ${z.dwell_threshold}s</div>
            <div class="item-actions">
              <button class="btn btn-xs btn-outline" data-action="rename-zone" data-camera-id="${escapeHtml(state.activeCamera)}" data-name="${escapeHtml(z.name)}" title="Rename zone">✏️</button>
              <button class="btn btn-xs btn-outline-danger" data-action="delete-zone" data-camera-id="${escapeHtml(state.activeCamera)}" data-name="${escapeHtml(z.name)}">🗑️</button>
            </div>
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
              <strong>${escapeHtml(tw.name)}</strong>
              <span class="badge">${tw.bidirectional ? 'IN/OUT' : 'One-Way'}</span>
            </div>
            <div class="item-sub">(${tw.line_segment[0][0]}, ${tw.line_segment[0][1]}) -> (${tw.line_segment[1][0]}, ${tw.line_segment[1][1]})</div>
            <div class="item-actions">
              <button class="btn btn-xs btn-outline" data-action="rename-tripwire" data-camera-id="${escapeHtml(state.activeCamera)}" data-name="${escapeHtml(tw.name)}" title="Rename tripwire">✏️</button>
              <button class="btn btn-xs btn-outline-danger" data-action="delete-tripwire" data-camera-id="${escapeHtml(state.activeCamera)}" data-name="${escapeHtml(tw.name)}">🗑️</button>
            </div>
          </div>
        `).join('');
    }
  }

  function renderTopologyLinksUI() {
    bindDelegatedScenarioActions();
    const state = _getState();
    const listEl = document.getElementById('topology-links-list');
    if (!listEl) return;

    listEl.innerHTML = state.topologyLinks.length === 0
      ? '<div class="empty-state">No transition links registered. Click + Add Spatial Transition.</div>'
      : state.topologyLinks.map((l) => `
        <div class="topology-link-card glass-panel">
          <div class="link-flow">
            <span class="cam-badge">${escapeHtml(l.source_camera)}</span>
            <span class="zone-badge">${escapeHtml(l.source_zone)}</span>
            <span class="arrow">${l.bidirectional ? '⟷' : '⟶'}</span>
            <span class="cam-badge">${escapeHtml(l.target_camera)}</span>
            <span class="zone-badge">${escapeHtml(l.target_zone)}</span>
          </div>
          <div class="link-timing">
            <span>Transit Window: <strong>${l.t_min}s – ${l.t_max}s</strong></span> •
            <span>Prior Boost: <strong>+${(l.prior_boost * 100).toFixed(0)}%</strong></span>
          </div>
          <button class="btn btn-xs btn-outline-danger" data-action="delete-topology-link" data-link-id="${escapeHtml(l.link_id)}">🗑️ Remove</button>
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

