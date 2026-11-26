/**
 * Intelligent Tracker - Camera Form & Payload Helpers.
 * Extracted from camera_manager.js to keep module size < 350L.
 */
(function () {
  'use strict';

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function inferCameraType(source, explicitType) {
    const t = String(explicitType || '').trim().toLowerCase();
    if (['rtsp', 'usb', 'video_file', 'synthetic'].includes(t)) return t;
    const s = String(source || '').trim().toLowerCase();
    if (s === 'synthetic' || s === 'mock') return 'synthetic';
    if (/^\d+$/.test(s) || s === 'real') return 'usb';
    if (/\.(mp4|avi|mkv|mov|webm)$/i.test(s)) return 'video_file';
    return 'rtsp';
  }

  function buildCameraPayload({ id, name, source, camType, editingCamera, aiConfig }) {
    const cfg = aiConfig || {
      detector: document.getElementById('cam-detector-select')?.value || 'yolov8',
      tracker: document.getElementById('cam-tracker-select')?.value || 'centroid',
      confidence: 0.40,
      classes: null,
      tracked_categories: null,
      armed: false,
    };
    return {
      id,
      name,
      source,
      type: inferCameraType(source, camType),
      detector: cfg.detector || 'yolov8',
      tracker: cfg.tracker || 'centroid',
      confidence: cfg.confidence !== undefined ? cfg.confidence : 0.40,
      classes: cfg.classes,
      tracked_categories: cfg.tracked_categories ?? null,
      armed: Boolean(cfg.armed),
      enabled: editingCamera ? editingCamera.enabled !== false : true,
    };
  }

  function syncTrackedCategoriesUI(capabilities) {
    const classesInput = document.getElementById('cam-classes-input');
    const classesLabel = document.querySelector('label[for="cam-classes-input"]');
    if (classesLabel) classesLabel.textContent = 'Detector Classes (COCO) (comma-separated, empty for all)';
    if (!classesInput || document.getElementById('cam-tracked-categories-group')) return;
    const parentGroup = classesInput.closest?.('.form-group') || classesInput.parentElement;
    if (!parentGroup || !parentGroup.parentNode || typeof document.createElement !== 'function') return;
    const wrap = document.createElement('div');
    wrap.className = 'form-group';
    wrap.id = 'cam-tracked-categories-group';
    const cats = Array.isArray(capabilities?.tracked_categories) ? capabilities.tracked_categories : [];
    const chips = cats.map(c => `<button type="button" class="btn-tag-preset btn-cat-chip" data-cat="${escapeHtml(c.id)}">${escapeHtml(c.name || c.id)}</button>`).join('');
    wrap.innerHTML = '<label for="cam-tracked-categories-input">Tracked Gallery Categories (semantic Re-ID filter, empty for all)</label>'
      + '<input type="text" id="cam-tracked-categories-input" class="form-input" placeholder="e.g. vip, staff, restricted" />'
      + (chips ? `<div class="class-presets-bar">${chips}</div>` : '');
    parentGroup.parentNode.insertBefore(wrap, parentGroup.nextSibling);
    wrap.querySelectorAll?.('.btn-cat-chip')?.forEach(btn => btn.addEventListener('click', () => {
      const inp = document.getElementById('cam-tracked-categories-input');
      if (!inp) return;
      const val = btn.getAttribute('data-cat');
      const cur = inp.value.split(',').map(s => s.trim()).filter(Boolean);
      const idx = cur.indexOf(val);
      if (idx >= 0) cur.splice(idx, 1); else cur.push(val);
      inp.value = cur.join(', ');
      btn.classList.toggle('active', idx < 0);
    }));
  }

  function applyDiscoverySelection({ id, name, source, type }, els) {
    if (els.inputCamId && !els.editingCameraId) els.inputCamId.value = id || '';
    if (els.inputCamName) els.inputCamName.value = name || '';
    if (els.inputCamSource) els.inputCamSource.value = source || '';
    if (els.selectCamType && type) els.selectCamType.value = inferCameraType(source, type);
  }

  function resetCameraFormState(els) {
    if (els.camForm) els.camForm.reset();
    if (els.inputCamId) {
      els.inputCamId.readOnly = false;
      els.inputCamId.disabled = false;
    }
    if (els.selectCamType) els.selectCamType.value = 'rtsp';
    if (els.inputCamPort) els.inputCamPort.value = '554';
    if (els.inputCamChannel) els.inputCamChannel.value = '1';
    const btnSave = document.getElementById('btn-save-camera');
    if (btnSave) btnSave.textContent = '💾 Save Camera to VMS';
    const testImg = document.getElementById('test-preview-img');
    const testMeta = document.getElementById('test-preview-meta');
    if (testImg) {
      if (window.MediaEmptyState) window.MediaEmptyState.showEmpty(testImg, 'No Test Snapshot', 'Click Test Connection to preview.', true);
      else { testImg.removeAttribute?.('src'); testImg.style.display = 'none'; }
    }
    if (testMeta) testMeta.textContent = 'Click "Test Connection" to verify source.';
  }

  window.CameraFormHelpers = {
    escapeHtml,
    inferCameraType,
    buildCameraPayload,
    applyDiscoverySelection,
    resetCameraFormState,
    syncTrackedCategoriesUI,
  };
})();
