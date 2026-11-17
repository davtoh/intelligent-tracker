/**
 * Intelligent Tracker - Multi-Layer Overlay Toolbar UI & Keyboard Navigation.
 *
 * Renders accessible toggle chips in #scrubber-overlay-layers, announces state
 * updates via live region, and provides roving-tabindex fallback when native
 * focusgroup is unavailable.
 */

(function () {
  'use strict';

  let keyNavBound = false;

  const FEATURE_TOGGLES = [
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

  function announceStatus(message) {
    const statusEl = document.getElementById('scrubber-overlay-layers-status');
    if (statusEl) statusEl.textContent = message;
  }

  function setupToolbarKeyboardFallback(container) {
    if (keyNavBound || !container || 'focusGroup' in HTMLElement.prototype) return;
    keyNavBound = true;

    container.addEventListener('focusin', (e) => {
      const btn = e.target.closest('button');
      if (!btn || !container.contains(btn)) return;
      container.querySelectorAll('button').forEach((item) => {
        item.tabIndex = item === btn ? 0 : -1;
      });
    });

    container.addEventListener('keydown', (e) => {
      const buttons = Array.from(container.querySelectorAll('button'));
      const currentIdx = buttons.indexOf(document.activeElement);
      if (currentIdx === -1 || buttons.length === 0) return;

      const rtl = getComputedStyle(container).direction === 'rtl';
      const stepMap = { ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1 };
      let nextIdx = null;
      if (e.key in stepMap) nextIdx = (currentIdx + stepMap[e.key] + buttons.length) % buttons.length;
      else if (e.key === 'Home') nextIdx = 0;
      else if (e.key === 'End') nextIdx = buttons.length - 1;
      if (nextIdx === null) return;

      e.preventDefault();
      buttons.forEach((b, idx) => { b.tabIndex = idx === nextIdx ? 0 : -1; });
      buttons[nextIdx].focus();
    });
  }

  function syncToolbarTabIndices(container) {
    if (!container || 'focusGroup' in HTMLElement.prototype) return;
    container.querySelectorAll('button').forEach((btn, idx) => {
      btn.tabIndex = idx === 0 ? 0 : -1;
    });
  }

  function renderChipHtml(desc, isActive) {
    const pressed = isActive ? 'true' : 'false';
    return `
      <button
        type="button"
        class="overlay-layer-chip"
        data-run-id="${escapeHtml(desc.runId)}"
        data-palette="${escapeHtml(desc.palette.id)}"
        aria-pressed="${pressed}"
        title="${escapeHtml(desc.title)}"
      >
        <span class="overlay-layer-swatch" aria-hidden="true"></span>
        <span class="overlay-layer-chip-text">${escapeHtml(desc.label)}</span>
      </button>
    `;
  }

  function renderFeaturePillsHtml(featureVisibility) {
    const vis = featureVisibility
      || window.ScrubberOverlay?.getFeatureVisibility?.()
      || window.UnifiedCanvasOverlay?.DEFAULT_VISIBILITY
      || { bboxes: true, track_ids: true, dwell_timers: true, velocity: false, zones: true, tripwires: true };
    const pills = FEATURE_TOGGLES.map((f) => {
      const pressed = vis[f.key] ? 'true' : 'false';
      return `<button type="button" class="overlay-feature-pill" data-feature-key="${f.key}" aria-pressed="${pressed}" title="${escapeHtml(f.title)}">${escapeHtml(f.label)}</button>`;
    }).join('');
    return `<span role="separator" aria-orientation="vertical" class="overlay-layers-separator"></span><div role="group" aria-label="Overlay feature toggles" class="overlay-feature-pills">${pills}</div>`;
  }

  function bindToolbarEvents(container, { onToggle, onSetAll, onToggleFeature }) {
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
        announceStatus(`${btn.textContent.trim()} ${next ? 'enabled' : 'disabled'}`);
      });
    });
  }

  function renderToolbar({ descriptors, activeRunIds, hasLiveJob, featureVisibility, onToggle, onSetAll, onToggleFeature }) {
    const container = document.getElementById('scrubber-overlay-layers');
    if (!container) return;

    if ((!descriptors || descriptors.length === 0) && !hasLiveJob) {
      container.innerHTML = '';
      container.hidden = true;
      return;
    }

    const chipsHtml = (descriptors || []).map((d) => renderChipHtml(d, activeRunIds.has(d.runId))).join('');
    const liveHtml = hasLiveJob
      ? '<span class="overlay-layer-live-pill" title="Live progressive detection stream active">● Live Stream</span>'
      : '';
    const bulkHtml = descriptors.length >= 2
      ? `
        <span role="separator" aria-orientation="vertical" class="overlay-layers-separator"></span>
        <div role="group" aria-label="Layer bulk actions" class="overlay-layers-actions">
          <button type="button" class="btn btn-xs btn-outline overlay-layer-action-btn" data-layer-action="all" title="Show all detection layers">All</button>
          <button type="button" class="btn btn-xs btn-outline overlay-layer-action-btn" data-layer-action="none" title="Hide all detection layers">Clear</button>
        </div>
      `
      : '';

    container.innerHTML = `
      <span class="overlay-layers-label">👁️ Layers:</span>
      <div role="group" aria-label="Detection run layers" class="overlay-layers-chips">${chipsHtml}${liveHtml}</div>
      ${bulkHtml}
      ${renderFeaturePillsHtml(featureVisibility)}
    `;
    container.hidden = false;

    bindToolbarEvents(container, { onToggle, onSetAll, onToggleFeature });
    setupToolbarKeyboardFallback(container);
    syncToolbarTabIndices(container);
  }

  function updateChipStates(activeRunIds) {
    const container = document.getElementById('scrubber-overlay-layers');
    if (!container) return;
    container.querySelectorAll('.overlay-layer-chip[data-run-id]').forEach((btn) => {
      const rid = btn.getAttribute('data-run-id');
      btn.setAttribute('aria-pressed', activeRunIds.has(rid) ? 'true' : 'false');
    });
  }

  window.OverlayLayerToolbar = {
    FEATURE_TOGGLES,
    announceStatus,
    renderToolbar,
    updateChipStates,
  };
})();

