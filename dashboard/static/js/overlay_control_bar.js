/**
 * Intelligent Tracker - Unified OverlayControlBar Component (P2-26).
 *
 * Reusable overlay toolbar supporting:
 * - variant: 'live' (Live Monitor OverlayConfig checkboxes + BEV PiP toggle)
 * - variant: 'scrubber' (Video Studio run layer chips + feature visibility pills)
 */

(function () {
  'use strict';

  const LIVE_TOGGLES = [
    { key: 'bboxes', label: '📦 Boxes', title: 'Toggle Object Bounding Boxes', defaultChecked: true },
    { key: 'track_ids', label: '🏷️ IDs', title: 'Toggle Track IDs and Recognized Names', defaultChecked: true },
    { key: 'dwell_timers', label: '⏱️ Dwell', title: 'Toggle Zone Dwell Time Timers', defaultChecked: true },
    { key: 'velocity', label: '↗️ Velocity', title: 'Toggle Kinematic Velocity Movement Vectors', defaultChecked: false },
    { key: 'zones', label: '🟢 Zones', title: 'Toggle Spatial Polygonal Zones', defaultChecked: true },
    { key: 'tripwires', label: '⚡ Tripwires', title: 'Toggle Directional Virtual Tripwires', defaultChecked: true },
    { key: 'heatmap', label: '🔥 Heatmap', title: 'Toggle Real-Time Density Heatmap Overlay', defaultChecked: false },
    { key: 'bev_minimap', label: '🗺️ BEV Minimap', title: 'Toggle 2D Bird\'s-Eye Minimap Picture-in-Picture', defaultChecked: false },
    { key: 'hud_bar', label: 'ℹ️ Top HUD', title: 'Toggle Top Status HUD Information Bar', defaultChecked: true },
    { key: 'clutter', label: '🧹 De-clutter', title: 'Toggle Smart Label De-cluttering', defaultChecked: false },
  ];

  const SCRUBBER_FEATURE_TOGGLES = [
    { key: 'bboxes', label: 'BBoxes', title: 'Toggle bounding boxes' },
    { key: 'track_ids', label: 'IDs', title: 'Toggle track IDs & labels' },
    { key: 'dwell_timers', label: 'Dwell', title: 'Toggle dwell timers' },
    { key: 'velocity', label: 'Velocity', title: 'Toggle velocity vectors' },
    { key: 'zones', label: 'Zones', title: 'Toggle zone polygons' },
    { key: 'tripwires', label: 'Tripwires', title: 'Toggle tripwire lines' },
  ];

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderLiveBar(container, { values = {}, onToggle } = {}) {
    if (!container) return;
    const chipsHtml = LIVE_TOGGLES.map((item) => {
      const checked = item.key in values ? Boolean(values[item.key]) : item.defaultChecked;
      return `<label class="overlay-toggle-chip" title="${escapeHtml(item.title)}">`
        + `<input type="checkbox" id="overlay-toggle-${item.key}"${checked ? ' checked' : ''} />`
        + `<span>${item.label}</span></label>`;
    }).join('');
    container.innerHTML = `<div class="overlay-toolbar-label"><span>👁️ Video Overlays:</span></div>`
      + `<div class="overlay-toggles-row">${chipsHtml}</div>`;
    LIVE_TOGGLES.forEach((item) => {
      const input = document.getElementById(`overlay-toggle-${item.key}`);
      input?.addEventListener('change', (e) => onToggle?.(item.key, Boolean(e.target.checked)));
    });
  }

  function renderChipHtml(desc, isActive) {
    const pressed = isActive ? 'true' : 'false';
    return `<button type="button" class="overlay-layer-chip" data-run-id="${escapeHtml(desc.runId)}"`
      + ` data-palette="${escapeHtml(desc.palette?.id || 'cyan')}" aria-pressed="${pressed}" title="${escapeHtml(desc.title)}">`
      + `<span class="overlay-layer-swatch" aria-hidden="true"></span>`
      + `<span class="overlay-layer-chip-text">${escapeHtml(desc.label)}</span></button>`;
  }

  function renderFeaturePillsHtml(featureVisibility) {
    const vis = featureVisibility
      || window.ScrubberOverlay?.getFeatureVisibility?.()
      || window.UnifiedCanvasOverlay?.DEFAULT_VISIBILITY
      || { bboxes: true, track_ids: true, dwell_timers: true, velocity: false, zones: true, tripwires: true };
    const pills = SCRUBBER_FEATURE_TOGGLES.map((f) => {
      const pressed = vis[f.key] ? 'true' : 'false';
      return `<button type="button" class="overlay-feature-pill" data-feature-key="${f.key}"`
        + ` aria-pressed="${pressed}" title="${escapeHtml(f.title)}">${escapeHtml(f.label)}</button>`;
    }).join('');
    return `<span role="separator" aria-orientation="vertical" class="overlay-layers-separator"></span>`
      + `<div role="group" aria-label="Overlay feature toggles" class="overlay-feature-pills">${pills}</div>`;
  }

  function bindScrubberEvents(container, { onToggle, onSetAll, onToggleFeature, onAnnounce }) {
    container.querySelectorAll('.overlay-layer-chip[data-run-id]').forEach((btn) => {
      btn.addEventListener('click', () => onToggle?.(btn.getAttribute('data-run-id')));
    });
    container.querySelectorAll('.overlay-layer-action-btn').forEach((btn) => {
      btn.addEventListener('click', () => onSetAll?.(btn.getAttribute('data-layer-action') === 'all'));
    });
    container.querySelectorAll('.overlay-feature-pill').forEach((btn) => {
      btn.addEventListener('click', () => {
        const key = btn.getAttribute('data-feature-key');
        const next = btn.getAttribute('aria-pressed') !== 'true';
        btn.setAttribute('aria-pressed', next ? 'true' : 'false');
        if (typeof onToggleFeature === 'function') onToggleFeature(key, next);
        else window.ScrubberOverlay?.setFeatureVisibility?.(key, next);
        onAnnounce?.(`${btn.textContent.trim()} ${next ? 'enabled' : 'disabled'}`);
      });
    });
  }

  function renderScrubberBar(container, opts = {}) {
    if (!container) return;
    const { descriptors = [], activeRunIds = new Set(), hasLiveJob = false, showFeaturePills = false, featureVisibility } = opts;
    if (descriptors.length === 0 && !hasLiveJob && !showFeaturePills) {
      container.innerHTML = '';
      container.hidden = true;
      return;
    }
    const chipsHtml = descriptors.map((d) => renderChipHtml(d, activeRunIds.has(d.runId))).join('');
    const liveHtml = hasLiveJob
      ? '<span class="overlay-layer-live-pill" title="Live progressive detection stream active">● Live Stream</span>'
      : '';
    const bulkHtml = descriptors.length >= 2
      ? '<span role="separator" aria-orientation="vertical" class="overlay-layers-separator"></span>'
        + '<div role="group" aria-label="Layer bulk actions" class="overlay-layers-actions">'
        + '<button type="button" class="btn btn-xs btn-outline overlay-layer-action-btn" data-layer-action="all" title="Show all detection layers">All</button>'
        + '<button type="button" class="btn btn-xs btn-outline overlay-layer-action-btn" data-layer-action="none" title="Hide all detection layers">Clear</button></div>'
      : '';
    container.innerHTML = `<span class="overlay-layers-label">👁️ Layers:</span>`
      + `<div role="group" aria-label="Detection run layers" class="overlay-layers-chips">${chipsHtml}${liveHtml}</div>`
      + `${bulkHtml}${renderFeaturePillsHtml(featureVisibility)}`;
    container.hidden = false;
    bindScrubberEvents(container, opts);
  }

  function mount(options = {}) {
    const container = typeof options.container === 'string'
      ? document.getElementById(options.container)
      : options.container;
    if (!container) return;
    if (options.variant === 'scrubber') renderScrubberBar(container, options);
    else renderLiveBar(container, options);
  }

  window.OverlayControlBar = {
    LIVE_TOGGLES,
    SCRUBBER_FEATURE_TOGGLES,
    mount,
    renderLiveBar,
    renderScrubberBar,
  };
})();
