/**
 * Intelligent Tracker - Camera Manager & Multi-Camera VMS Controller.
 * 
 * Provides:
 * - Dynamic multi-camera grid switcher coordination
 * - Auto-discovery scanner coordination & preset URL generation
 * - Hot-add, edit, toggle, and removal of camera streams
 * - Modal configuration dialog management
 */

(function () {
  'use strict';

  let activeCameras = [];
  let cameraPresets = [];
  let focusedCameraId = 'cam_01';
  let editingCameraId = null;
  let selectedDeviceName = null;

  // Modal Elements & Inputs
  const modalCameraManager = document.getElementById('modal-camera-manager');
  const btnOpenCamManager = document.getElementById('btn-manage-cameras');
  const btnCloseCamManager = document.getElementById('modal-cam-close');
  const btnScanDevices = document.getElementById('btn-scan-devices');
  const activeCamerasTableBody = document.getElementById('active-cameras-table-body');
  const presetSelect = document.getElementById('cam-preset-select');
  const camForm = document.getElementById('camera-config-form');
  const btnTestConnection = document.getElementById('btn-test-connection');
  const cameraSelectDropdown = document.getElementById('active-camera-select');
  const inputCamId = document.getElementById('cam-id-input');
  const inputCamName = document.getElementById('cam-name-input');
  const inputCamIp = document.getElementById('cam-ip-input');
  const inputCamPort = document.getElementById('cam-port-input');
  const inputCamUser = document.getElementById('cam-user-input');
  const inputCamPass = document.getElementById('cam-pass-input');
  const inputCamChannel = document.getElementById('cam-channel-input');
  const selectCamStream = document.getElementById('cam-stream-select');
  const inputCamSource = document.getElementById('cam-source-input');

  function showToast(message, type = 'info') {
    if (typeof window.showToast === 'function') {
      window.showToast(message, type);
    } else {
      alert(message);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function init() {
    bindEvents();
    await loadPresets();
    await refreshCameras();
  }

  function bindDiscoveryControls() {
    if (btnScanDevices) {
      btnScanDevices.addEventListener('click', () => {
        window.CameraDiscovery?.scanDevices(({ id, name, source, device_name }) => {
          if (inputCamId && !editingCameraId) inputCamId.value = id;
          if (inputCamName) inputCamName.value = name;
          if (inputCamSource) inputCamSource.value = source;
          selectedDeviceName = device_name || name;
          window.CameraDiscovery?.testConnection();
        });
      });
    }

    const btnReleaseCameras = document.getElementById('btn-release-cameras');
    if (btnReleaseCameras) {
      btnReleaseCameras.addEventListener('click', () => {
        window.CameraDiscovery?.releaseCameras?.();
      });
    }

    [presetSelect, inputCamIp, inputCamPort, inputCamUser, inputCamPass, inputCamChannel, selectCamStream].forEach(elem => {
      if (elem) {
        elem.addEventListener('input', () => window.CameraDiscovery?.updatePresetUrl());
        elem.addEventListener('change', () => window.CameraDiscovery?.updatePresetUrl());
      }
    });

    if (btnTestConnection) {
      btnTestConnection.addEventListener('click', () => window.CameraDiscovery?.testConnection());
    }
  }

  function bindEvents() {
    document.querySelectorAll('.grid-switch-btn').forEach(btn => {
      btn.addEventListener('click', (e) => setGridMode(e.currentTarget.getAttribute('data-grid')));
    });

    if (cameraSelectDropdown) {
      cameraSelectDropdown.addEventListener('change', (e) => focusCamera(e.target.value));
    }

    if (btnOpenCamManager) btnOpenCamManager.addEventListener('click', openModal);
    if (btnCloseCamManager) btnCloseCamManager.addEventListener('click', closeModal);
    if (modalCameraManager) {
      modalCameraManager.addEventListener('click', (e) => {
        if (e.target === modalCameraManager) closeModal();
      });
    }

    bindDiscoveryControls();
    if (camForm) camForm.addEventListener('submit', saveCamera);
  }

  function openModal() {
    if (modalCameraManager) modalCameraManager.style.display = 'flex';
    refreshCameras();
  }

  function closeModal() {
    if (modalCameraManager) modalCameraManager.style.display = 'none';
    resetForm();
  }

  function resetForm() {
    editingCameraId = null;
    selectedDeviceName = null;
    if (camForm) camForm.reset();
    if (inputCamId) {
      inputCamId.readOnly = false;
      inputCamId.disabled = false;
    }
    if (inputCamPort) inputCamPort.value = '554';
    if (inputCamChannel) inputCamChannel.value = '1';
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

  async function loadPresets() {
    try {
      const resp = await fetch('/api/cameras/presets');
      if (resp.ok) {
        cameraPresets = await resp.json();
        if (presetSelect) {
          presetSelect.innerHTML = cameraPresets.map(p =>
            `<option value="${p.id}">${escapeHtml(p.name)}</option>`
          ).join('');
        }
      }
    } catch (e) {
      console.warn('Could not load camera presets:', e);
    }
  }

  async function refreshCameras() {
    try {
      const resp = await fetch('/api/cameras');
      if (resp.ok) {
        activeCameras = await resp.json();
        renderActiveCamerasTable();
        updateCameraDropdown();
        window.CameraGrid?.renderGrid(activeCameras, focusedCameraId, focusCamera);
      }
    } catch (e) {
      console.warn('Could not fetch active cameras:', e);
    }
  }

  function updateCameraDropdown() {
    if (!cameraSelectDropdown) return;
    cameraSelectDropdown.innerHTML = activeCameras.map(c =>
      `<option value="${c.id}" ${c.id === focusedCameraId ? 'selected' : ''}>${escapeHtml(c.name)} (${c.id})</option>`
    ).join('');
  }

  function renderActiveCamerasTable() {
    if (!activeCamerasTableBody) return;
    if (activeCameras.length === 0) {
      activeCamerasTableBody.innerHTML = '<tr><td colspan="6" class="text-center">No camera channels configured.</td></tr>';
      return;
    }

    activeCamerasTableBody.innerHTML = activeCameras.map(c => `
      <tr>
        <td><strong>${escapeHtml(c.id)}</strong></td>
        <td>${escapeHtml(c.name)}</td>
        <td><code class="source-code">${escapeHtml(String(c.source))}</code></td>
        <td>
          <span class="status-indicator ${c.status === 'online' ? 'online' : (c.status === 'paused' ? 'paused' : 'offline')}"></span>
          ${escapeHtml(c.status.toUpperCase())} (${c.fps} FPS)
        </td>
        <td>
          <button class="btn btn-xs ${c.enabled ? 'btn-outline' : 'btn-primary'} btn-toggle-cam" data-id="${c.id}">
            ${c.enabled ? '⏸ Pause' : '▶ Enable'}
          </button>
        </td>
        <td>
          <button class="btn btn-xs btn-outline btn-edit-cam" data-id="${c.id}" title="Edit Camera Settings">✏️</button>
          <button class="btn btn-xs btn-outline btn-focus-cam" data-id="${c.id}" title="Focus Camera">🔍</button>
          ${c.status === 'error' ? `<button class="btn btn-xs btn-outline btn-diag-cam" data-id="${c.id}" title="Inspect Error Trace" style="color: #f87171; border-color: rgba(239, 68, 68, 0.5);">🛠️</button>` : ''}
          <button class="btn btn-xs btn-danger btn-delete-cam" data-id="${c.id}" title="Delete Camera">🗑️</button>
        </td>
      </tr>
    `).join('');

    bindTableActionButtons();
  }

  function editCamera(id) {
    const cam = activeCameras.find(c => c.id === id);
    if (!cam) return;

    openModal();
    editingCameraId = id;
    selectedDeviceName = cam.device_name || null;

    if (inputCamId) {
      inputCamId.value = cam.id;
      inputCamId.disabled = true;
    }
    if (inputCamName) inputCamName.value = cam.name || '';
    if (inputCamSource) inputCamSource.value = cam.source || '';
    if (presetSelect && cam.type) presetSelect.value = cam.type;

    const btnSave = document.getElementById('btn-save-camera');
    if (btnSave) btnSave.textContent = '💾 Update Camera';
    showToast(`Editing camera '${cam.name}' (${id})`, 'info');
  }

  function bindTableActionButtons() {
    activeCamerasTableBody.querySelectorAll('.btn-edit-cam').forEach(btn => {
      btn.addEventListener('click', () => editCamera(btn.getAttribute('data-id')));
    });

    activeCamerasTableBody.querySelectorAll('.btn-diag-cam').forEach(btn => {
      btn.addEventListener('click', () => {
        window.CameraDiagnosticsUI?.openDiagnosticModal(btn.getAttribute('data-id'));
      });
    });

    activeCamerasTableBody.querySelectorAll('.btn-toggle-cam').forEach(btn => {
      btn.addEventListener('click', async () => {
        await fetch(`/api/cameras/${btn.getAttribute('data-id')}/toggle`, { method: 'POST' });
        await refreshCameras();
      });
    });

    activeCamerasTableBody.querySelectorAll('.btn-focus-cam').forEach(btn => {
      btn.addEventListener('click', () => {
        focusCamera(btn.getAttribute('data-id'));
        closeModal();
      });
    });

    activeCamerasTableBody.querySelectorAll('.btn-delete-cam').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        if (confirm(`Remove camera stream '${id}'?`)) {
          await fetch(`/api/cameras/${id}`, { method: 'DELETE' });
          await refreshCameras();
        }
      });
    });
  }

  function buildCameraPayload(id, name, source) {
    return {
      id: id,
      name: name,
      source: source,
      type: presetSelect.value || 'rtsp',
      detector: document.getElementById('cam-detector-select')?.value || 'mock',
      tracker: document.getElementById('cam-tracker-select')?.value || 'centroid',
      enabled: true,
      device_name: selectedDeviceName,
    };
  }

  async function saveCamera(e) {
    e.preventDefault();
    const id = inputCamId.value.trim();
    const name = inputCamName.value.trim();
    const source = inputCamSource.value.trim();

    if (!id || !name || !source) {
      showToast('Please fill Camera ID, Name, and Video Source.', 'warning');
      return;
    }

    const payload = buildCameraPayload(id, name, source);
    try {
      const url = editingCameraId ? `/api/cameras/${encodeURIComponent(editingCameraId)}` : '/api/cameras';
      const method = editingCameraId ? 'PUT' : 'POST';
      const resp = await fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (resp.ok) {
        showToast(editingCameraId ? `Camera '${name}' updated!` : `Camera '${name}' added!`, 'success');
        resetForm();
        closeModal();
        await refreshCameras();
        focusCamera(id);
      } else {
        const err = await resp.json();
        showToast(`Failed to save camera: ${err.detail || 'Unknown error'}`, 'error');
      }
    } catch (err) {
      showToast(`Error saving camera: ${err.message}`, 'error');
    }
  }

  function focusCamera(cameraId) {
    focusedCameraId = cameraId;
    window.CameraGrid?.focusCamera(cameraId, activeCameras, focusCamera);
  }

  function setGridMode(mode) {
    window.CameraGrid?.setGridMode(mode, activeCameras, focusedCameraId, focusCamera);
  }

  const cleanupMultiGrid = () => {
    const mg = document.getElementById('multi-grid-container');
    if (mg) mg.innerHTML = '';
  };
  window.addEventListener('beforeunload', cleanupMultiGrid);
  window.addEventListener('pagehide', cleanupMultiGrid);

  window.CameraManager = {
    init: init,
    refreshCameras: refreshCameras,
    focusCamera: focusCamera,
    setGridMode: setGridMode,
    editCamera: editCamera,
    openModal: openModal,
    closeModal: closeModal,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
