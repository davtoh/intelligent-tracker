/**
 * Intelligent Tracker - Camera AI Configuration & Capabilities Module.
 * 
 * Coordinates:
 * - Dynamic system capabilities loading (/api/system/capabilities)
 * - Detector and tracker dropdown population
 * - Confidence slider/numeric two-way synchronization
 * - Class tag presets (person, vehicles, security, all)
 * - Quick real camera device source assignment
 */

(function () {
  'use strict';

  const MOCK_DEMO_LABEL = '🧪 Synthetic Mock (Demo Simulation Only)';
  let capabilities = null;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function isSyntheticSource(source, camType) {
    if (camType !== undefined && camType !== null) {
      if (['synthetic', 'mock', 'demo'].includes(String(camType).trim().toLowerCase())) return true;
    }
    if (source === undefined || source === null) return true;
    const norm = String(source).trim().toLowerCase();
    return norm === '' || ['synthetic', 'mock', 'demo'].includes(norm);
  }

  function syncMockOptionLabel() {
    const detSelect = document.getElementById('cam-detector-select');
    if (!detSelect) return;
    const fromOpts = Array.from(detSelect.options || []);
    const fromQuery = typeof detSelect.querySelectorAll === 'function' ? Array.from(detSelect.querySelectorAll('option')) : [];
    [...fromOpts, ...fromQuery].forEach(opt => {
      if (opt && opt.value === 'mock') opt.textContent = MOCK_DEMO_LABEL;
    });
  }

  async function loadCapabilities() {
    try {
      const resp = await fetch('/api/system/capabilities');
      if (resp.ok) {
        capabilities = await resp.json();
        populateSelectOptions();
      }
    } catch (e) {
      console.warn('Could not load system AI capabilities:', e);
    }
  }

  function populateDetectorOptions(detSelect) {
    const currentVal = detSelect.value || 'yolov8';
    const primary = capabilities.primary_detectors || ['yolov8', 'yolo11', 'haar', 'face_yunet', 'movementdetector', 'mock'];
    const labels = {
      yolov8: 'YOLOv8 (High Accuracy)', yolo11: 'YOLO11 (SOTA Real-time)',
      haar: 'Haar Cascade (Ultra Fast)', face_yunet: 'YuNet (Face Detection)',
      movementdetector: 'Movement (Frame Diff)', mock: MOCK_DEMO_LABEL,
      color: 'Color / HSV Filter', edgetpu: 'Coral EdgeTPU', onnx: 'Generic ONNX Model',
    };
    const renderOpt = (d, fallback) =>
      `<option value="${d}" ${d === currentVal ? 'selected' : ''}>${escapeHtml(labels[d] || fallback)}</option>`;
    const primaryHtml = primary.map(d => renderOpt(d, d.toUpperCase())).join('');
    const otherHtml = capabilities.detectors.filter(d => !primary.includes(d)).map(d => renderOpt(d, d)).join('');
    detSelect.innerHTML = primaryHtml + (otherHtml ? `<optgroup label="Other Detectors">${otherHtml}</optgroup>` : '');
    detSelect.value = currentVal;
  }

  function populateSelectOptions() {
    if (!capabilities) return;
    const detSelect = document.getElementById('cam-detector-select');
    if (detSelect && capabilities.detectors) populateDetectorOptions(detSelect);
    const trackerSelect = document.getElementById('cam-tracker-select');
    if (trackerSelect && capabilities.trackers) {
      const currentVal = trackerSelect.value || 'centroid';
      const trackerLabels = { centroid: 'Centroid (Fast Distance)', sort: 'SORT (Kalman + Hungarian)' };
      trackerSelect.innerHTML = capabilities.trackers.map(t =>
        `<option value="${t}" ${t === currentVal ? 'selected' : ''}>${escapeHtml(trackerLabels[t] || t.toUpperCase())}</option>`
      ).join('');
      trackerSelect.value = currentVal;
    }
  }

  function syncConfidence(val) {
    const num = Math.min(Math.max(parseFloat(val) || 0.40, 0.05), 1.00);
    const formatted = num.toFixed(2);
    const range = document.getElementById('cam-conf-range');
    const input = document.getElementById('cam-conf-input');
    const display = document.getElementById('cam-conf-display');
    if (range && range.value !== formatted) range.value = formatted;
    if (input && input.value !== formatted) input.value = formatted;
    if (display) display.textContent = formatted;
  }

  function handleSourceInputChange() {
    const sourceInput = document.getElementById('cam-source-input');
    const detSelect = document.getElementById('cam-detector-select');
    const raw = sourceInput ? String(sourceInput.value || '').trim() : '';
    if (raw && !isSyntheticSource(raw) && detSelect && detSelect.value === 'mock') {
      detSelect.value = 'yolov8';
      window.showToast?.('Synthetic Mock is reserved for Demo Simulation; switched detector to YOLOv8.', 'warning');
    }
  }

  function handleDetectorChange() {
    const detSelect = document.getElementById('cam-detector-select');
    const sourceInput = document.getElementById('cam-source-input');
    if (detSelect && detSelect.value === 'mock' && sourceInput) {
      if (String(sourceInput.value || '').trim().toLowerCase() !== 'synthetic') {
        sourceInput.value = 'synthetic';
        window.showToast?.('Demo Simulation Mode enabled: video source set to synthetic.', 'info');
      }
    }
  }

  function bindEvents() {
    const range = document.getElementById('cam-conf-range');
    const input = document.getElementById('cam-conf-input');
    if (range) range.addEventListener('input', (e) => syncConfidence(e.target.value));
    if (input) {
      input.addEventListener('input', (e) => syncConfidence(e.target.value));
      input.addEventListener('change', (e) => syncConfidence(e.target.value));
    }
    document.querySelectorAll('.btn-tag-preset').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const classesInput = document.getElementById('cam-classes-input');
        if (classesInput) classesInput.value = e.currentTarget.getAttribute('data-classes') || '';
        document.querySelectorAll('.btn-tag-preset').forEach(b => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
      });
    });
    const btnQuickReal = document.getElementById('btn-quick-real-cam');
    if (btnQuickReal) {
      btnQuickReal.addEventListener('click', () => {
        const inputCamSource = document.getElementById('cam-source-input');
        const inputCamName = document.getElementById('cam-name-input');
        if (inputCamSource) inputCamSource.value = 'real';
        if (inputCamName && !inputCamName.value.trim()) inputCamName.value = 'Physical Webcam';
        handleSourceInputChange();
        window.CameraDiscovery?.testConnection?.();
      });
    }
    const sourceInput = document.getElementById('cam-source-input');
    if (sourceInput) {
      sourceInput.addEventListener('input', handleSourceInputChange);
      sourceInput.addEventListener('change', handleSourceInputChange);
    }
    const detSelect = document.getElementById('cam-detector-select');
    if (detSelect) detSelect.addEventListener('change', handleDetectorChange);
  }

  function getValues() {
    const detSelect = document.getElementById('cam-detector-select');
    const trackerSelect = document.getElementById('cam-tracker-select');
    const confInput = document.getElementById('cam-conf-input');
    const classesInput = document.getElementById('cam-classes-input');
    const confVal = parseFloat(confInput?.value || '0.40');
    const classesRaw = (classesInput?.value || '').trim();
    return {
      detector: detSelect?.value || 'yolov8',
      tracker: trackerSelect?.value || 'centroid',
      confidence: isNaN(confVal) ? 0.40 : Math.min(Math.max(confVal, 0.05), 1.00),
      classes: classesRaw ? classesRaw.split(',').map(s => s.trim()).filter(Boolean) : null,
    };
  }

  function setValues(cam) {
    if (!cam) return;
    const detSelect = document.getElementById('cam-detector-select');
    if (detSelect && cam.detector) {
      const hasRealSrc = cam.source !== undefined && cam.source !== null && String(cam.source).trim() !== '' && !isSyntheticSource(cam.source, cam.type);
      detSelect.value = (cam.detector === 'mock' && hasRealSrc) ? 'yolov8' : cam.detector;
    }
    const trackerSelect = document.getElementById('cam-tracker-select');
    if (trackerSelect && cam.tracker) trackerSelect.value = cam.tracker;
    syncConfidence(cam.confidence !== undefined && cam.confidence !== null ? cam.confidence : 0.40);
    const classesInput = document.getElementById('cam-classes-input');
    if (classesInput) classesInput.value = Array.isArray(cam.classes) ? cam.classes.join(', ') : (cam.classes || '');
    const activeClasses = classesInput ? classesInput.value.trim() : '';
    document.querySelectorAll('.btn-tag-preset').forEach(btn => {
      btn.classList.toggle('active', (btn.getAttribute('data-classes') || '').trim() === activeClasses);
    });
  }

  function resetValues() {
    const detSelect = document.getElementById('cam-detector-select');
    if (detSelect) detSelect.value = 'yolov8';
    const trackerSelect = document.getElementById('cam-tracker-select');
    if (trackerSelect) trackerSelect.value = 'centroid';
    syncConfidence(0.40);
    const classesInput = document.getElementById('cam-classes-input');
    if (classesInput) classesInput.value = '';
    document.querySelectorAll('.btn-tag-preset').forEach(btn => btn.classList.remove('active'));
  }

  function resolveInitialCameraId(activeCameras, currentId = 'cam_01') {
    if (!Array.isArray(activeCameras) || activeCameras.length === 0) return currentId || 'cam_01';
    const existing = activeCameras.find(c => c && c.id === currentId);
    const targetCam = existing || activeCameras.find(c => c && c.enabled !== false && c.id) || activeCameras.find(c => c && c.id);
    if (!targetCam) return currentId || 'cam_01';
    const resolvedId = targetCam.id;
    const appActiveId = window.App?.getActiveCameraId?.();
    if (resolvedId !== currentId || (appActiveId && appActiveId !== resolvedId)) {
      const streamImg = document.getElementById('live-stream-img');
      if (streamImg) streamImg.src = `/stream/${resolvedId}`;
      const streamTitle = document.getElementById('video-stream-title');
      if (streamTitle) {
        const title = `Camera Feed: ${String(targetCam.name || resolvedId).toUpperCase()} (${resolvedId})`;
        streamTitle.textContent = title;
        streamTitle.title = title;
      }
      const camSelect = document.getElementById('active-camera-select');
      if (camSelect) camSelect.value = resolvedId;
      window.App?.switchCamera?.(resolvedId);
      window.CameraRecording?.onCameraFocused?.(resolvedId);
    }
    return resolvedId;
  }

  async function init() {
    syncMockOptionLabel();
    bindEvents();
    await loadCapabilities();
  }

  window.CameraAIConfig = {
    init: init,
    loadCapabilities: loadCapabilities,
    getValues: getValues,
    setValues: setValues,
    resetValues: resetValues,
    syncConfidence: syncConfidence,
    isSyntheticSource: isSyntheticSource,
    resolveInitialCameraId: resolveInitialCameraId,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

