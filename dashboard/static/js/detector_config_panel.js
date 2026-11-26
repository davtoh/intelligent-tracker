/**
 * Intelligent Tracker - Shared Detector Config Panel Controller.
 * Hydrates COCO class multi-select from /api/system/capabilities, manages
 * confidence slider/input sync, class presets, and agnostic_nms toggle.
 */
(function () {
  'use strict';

  function parseClassesList(raw) {
    const text = String(raw || '').trim();
    return text ? text.split(',').map((s) => s.trim()).filter(Boolean) : [];
  }

  function syncMultiSelectFromInput() {
    const sel = document.getElementById('cam-coco-class-select');
    const inp = document.getElementById('cam-classes-input');
    if (!sel || !inp) return;
    const active = new Set(parseClassesList(inp.value).map((c) => c.toLowerCase()));
    Array.from(sel.options || []).forEach((opt) => {
      opt.selected = active.has(String(opt.value || '').toLowerCase());
    });
  }

  function hydrateCocoClasses(capabilities) {
    const sel = document.getElementById('cam-coco-class-select');
    if (!sel) return;
    const classes = Array.isArray(capabilities?.coco_classes) ? capabilities.coco_classes : [];
    if (!classes.length) return;
    sel.innerHTML = classes.map((cls) => {
      const safe = String(cls).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
      return `<option value="${safe}">${safe}</option>`;
    }).join('');
    syncMultiSelectFromInput();
  }

  function bindPanelEvents() {
    const sel = document.getElementById('cam-coco-class-select');
    const inp = document.getElementById('cam-classes-input');
    if (sel && !sel.dataset?.bound) {
      if (sel.dataset) sel.dataset.bound = '1';
      sel.addEventListener('change', () => {
        if (!inp) return;
        const picked = Array.from(sel.selectedOptions || []).map((o) => o.value).filter(Boolean);
        inp.value = picked.join(', ');
      });
    }
    if (inp && !inp.dataset?.cocoBound) {
      if (inp.dataset) inp.dataset.cocoBound = '1';
      inp.addEventListener('input', syncMultiSelectFromInput);
    }
    const panel = document.getElementById('detector-config-panel');
    if (panel) {
      const presets = Array.from(panel.querySelectorAll('.btn-tag-preset'));
      presets.forEach((btn) => {
        if (btn.dataset?.panelPresetBound) return;
        if (btn.dataset) btn.dataset.panelPresetBound = '1';
        btn.addEventListener('click', () => {
          if (inp) inp.value = btn.getAttribute('data-classes') || '';
          syncMultiSelectFromInput();
          presets.forEach((b) => b.classList?.remove?.('active'));
          btn.classList?.add?.('active');
        });
      });
    }
  }

  function readValues() {
    const det = document.getElementById('cam-detector-select')?.value || 'yolov8';
    const trk = document.getElementById('cam-tracker-select')?.value || 'sort';
    const confVal = parseFloat(document.getElementById('cam-conf-input')?.value || '0.40');
    const classesList = parseClassesList(document.getElementById('cam-classes-input')?.value);
    const catsList = parseClassesList(document.getElementById('cam-tracked-categories-input')?.value);
    const armed = Boolean(document.getElementById('cam-armed-checkbox')?.checked);
    const nmsEl = document.getElementById('cam-agnostic-nms-checkbox');
    const agnosticNms = nmsEl ? Boolean(nmsEl.checked) : true;
    return {
      detector: det,
      tracker: trk,
      confidence: Number.isNaN(confVal) ? 0.40 : Math.min(Math.max(confVal, 0.05), 1.00),
      classes: classesList.length ? classesList : null,
      tracked_categories: catsList.length ? catsList : null,
      armed,
      agnostic_nms: agnosticNms,
    };
  }

  function applyValues(cam = {}) {
    const nmsEl = document.getElementById('cam-agnostic-nms-checkbox');
    if (nmsEl) nmsEl.checked = cam.agnostic_nms !== undefined ? Boolean(cam.agnostic_nms) : true;
    syncMultiSelectFromInput();
  }

  function resetPanel() {
    const nmsEl = document.getElementById('cam-agnostic-nms-checkbox');
    if (nmsEl) nmsEl.checked = true;
    syncMultiSelectFromInput();
  }

  window.DetectorConfigPanel = {
    hydrateCocoClasses,
    syncMultiSelectFromInput,
    bindPanelEvents,
    readValues,
    applyValues,
    resetPanel,
  };
})();
