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

  let capabilities = null;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
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

  function populateSelectOptions() {
    if (!capabilities) return;

    const detSelect = document.getElementById('cam-detector-select');
    if (detSelect && capabilities.detectors) {
      const currentVal = detSelect.value || 'yolov8';
      const primary = capabilities.primary_detectors || ['yolov8', 'yolo11', 'haar', 'face_yunet', 'movementdetector', 'mock'];
      
      const labels = {
        yolov8: 'YOLOv8 (High Accuracy)',
        yolo11: 'YOLO11 (SOTA Real-time)',
        haar: 'Haar Cascade (Ultra Fast)',
        face_yunet: 'YuNet (Face Detection)',
        movementdetector: 'Movement (Frame Diff)',
        mock: 'Synthetic Mock (Testing)',
        color: 'Color / HSV Filter',
        edgetpu: 'Coral EdgeTPU',
        onnx: 'Generic ONNX Model',
      };

      const primaryOptions = primary.map(d => 
        `<option value="${d}" ${d === currentVal ? 'selected' : ''}>${escapeHtml(labels[d] || d.toUpperCase())}</option>`
      );

      const otherDetectors = capabilities.detectors.filter(d => !primary.includes(d));
      const otherOptions = otherDetectors.map(d =>
        `<option value="${d}" ${d === currentVal ? 'selected' : ''}>${escapeHtml(labels[d] || d)}</option>`
      );

      detSelect.innerHTML = primaryOptions.join('') + 
        (otherOptions.length > 0 ? `<optgroup label="Other Detectors">${otherOptions.join('')}</optgroup>` : '');
      detSelect.value = currentVal;
    }

    const trackerSelect = document.getElementById('cam-tracker-select');
    if (trackerSelect && capabilities.trackers) {
      const currentVal = trackerSelect.value || 'centroid';
      const trackerLabels = {
        centroid: 'Centroid (Fast Distance)',
        sort: 'SORT (Kalman + Hungarian)',
      };
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

  function bindEvents() {
    const range = document.getElementById('cam-conf-range');
    const input = document.getElementById('cam-conf-input');

    if (range) {
      range.addEventListener('input', (e) => syncConfidence(e.target.value));
    }
    if (input) {
      input.addEventListener('input', (e) => syncConfidence(e.target.value));
      input.addEventListener('change', (e) => syncConfidence(e.target.value));
    }

    // Tag preset buttons
    document.querySelectorAll('.btn-tag-preset').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const classes = e.currentTarget.getAttribute('data-classes') || '';
        const classesInput = document.getElementById('cam-classes-input');
        if (classesInput) {
          classesInput.value = classes;
        }
        document.querySelectorAll('.btn-tag-preset').forEach(b => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
      });
    });

    // Quick Real Cam Preset Button
    const btnQuickReal = document.getElementById('btn-quick-real-cam');
    if (btnQuickReal) {
      btnQuickReal.addEventListener('click', () => {
        const inputCamSource = document.getElementById('cam-source-input');
        const inputCamName = document.getElementById('cam-name-input');
        if (inputCamSource) {
          inputCamSource.value = 'real';
        }
        if (inputCamName && !inputCamName.value.trim()) {
          inputCamName.value = 'Physical Webcam';
        }
        window.CameraDiscovery?.testConnection?.();
      });
    }
  }

  function getValues() {
    const detSelect = document.getElementById('cam-detector-select');
    const trackerSelect = document.getElementById('cam-tracker-select');
    const confInput = document.getElementById('cam-conf-input');
    const classesInput = document.getElementById('cam-classes-input');

    const detector = detSelect?.value || 'yolov8';
    const tracker = trackerSelect?.value || 'centroid';
    const confVal = parseFloat(confInput?.value || '0.40');
    const confidence = isNaN(confVal) ? 0.40 : Math.min(Math.max(confVal, 0.05), 1.00);

    const classesRaw = (classesInput?.value || '').trim();
    const classes = classesRaw
      ? classesRaw.split(',').map(s => s.trim()).filter(Boolean)
      : null;

    return { detector, tracker, confidence, classes };
  }

  function setValues(cam) {
    if (!cam) return;

    const detSelect = document.getElementById('cam-detector-select');
    if (detSelect && cam.detector) {
      detSelect.value = cam.detector;
    }

    const trackerSelect = document.getElementById('cam-tracker-select');
    if (trackerSelect && cam.tracker) {
      trackerSelect.value = cam.tracker;
    }

    const confVal = cam.confidence !== undefined && cam.confidence !== null ? cam.confidence : 0.40;
    syncConfidence(confVal);

    const classesInput = document.getElementById('cam-classes-input');
    if (classesInput) {
      if (Array.isArray(cam.classes)) {
        classesInput.value = cam.classes.join(', ');
      } else if (cam.classes) {
        classesInput.value = cam.classes;
      } else {
        classesInput.value = '';
      }
    }

    // Update active state on preset tag buttons
    const activeClasses = classesInput ? classesInput.value.trim() : '';
    document.querySelectorAll('.btn-tag-preset').forEach(btn => {
      const targetClasses = (btn.getAttribute('data-classes') || '').trim();
      if (targetClasses === activeClasses) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
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

  async function init() {
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
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

