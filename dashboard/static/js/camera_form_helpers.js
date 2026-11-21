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
      armed: Boolean(cfg.armed),
      enabled: editingCamera ? editingCamera.enabled !== false : true,
    };
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
      testImg.src = '';
      testImg.style.display = 'none';
    }
    if (testMeta) testMeta.textContent = 'Click "Test Connection" to verify source.';
  }

  window.CameraFormHelpers = {
    escapeHtml,
    inferCameraType,
    buildCameraPayload,
    applyDiscoverySelection,
    resetCameraFormState,
  };
})();
