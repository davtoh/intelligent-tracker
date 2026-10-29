/**
 * Intelligent Tracker - Camera Manager & Multi-Camera VMS Controller.
 * 
 * Provides:
 * - Dynamic multi-camera grid switcher (1x1, 2x2, 3x3)
 * - Auto-discovery scanner (USB Webcams, ONVIF WS-Discovery, LAN RTSP probe)
 * - Vendor RTSP presets & URL-encoded credential builder (Hikvision, Tapo, EZVIZ, Dahua, Generic)
 * - One-click connection test with live snapshot preview
 * - Hot-add, edit, toggle, and removal of camera streams
 */

(function () {
  'use strict';

  let activeCameras = [];
  let cameraPresets = [];
  let currentGridMode = '1x1'; // '1x1', '2x2', '3x3'
  let focusedCameraId = 'cam_01';

  // DOM Elements
  const multiGridContainer = document.getElementById('multi-grid-container');
  const singleVideoWrapper = document.getElementById('video-wrapper');
  const liveStreamImg = document.getElementById('live-stream-img');
  const streamTitle = document.getElementById('video-stream-title');
  const cameraSelectDropdown = document.getElementById('active-camera-select');

  // Modal Elements
  const modalCameraManager = document.getElementById('modal-camera-manager');
  const btnOpenCamManager = document.getElementById('btn-manage-cameras');
  const btnCloseCamManager = document.getElementById('modal-cam-close');
  const btnScanDevices = document.getElementById('btn-scan-devices');
  const discoveredDevicesList = document.getElementById('discovered-devices-list');
  const activeCamerasTableBody = document.getElementById('active-cameras-table-body');
  const presetSelect = document.getElementById('cam-preset-select');
  const camForm = document.getElementById('camera-config-form');
  const btnTestConnection = document.getElementById('btn-test-connection');
  const testPreviewImg = document.getElementById('test-preview-img');
  const testPreviewMeta = document.getElementById('test-preview-meta');

  // Input Fields for URL Builder
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

  // Initialize
  async function init() {
    bindEvents();
    await loadPresets();
    await refreshCameras();
  }

  function bindEvents() {
    // Grid switcher buttons
    document.querySelectorAll('.grid-switch-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const mode = e.currentTarget.getAttribute('data-grid');
        setGridMode(mode);
      });
    });

    // Camera selector dropdown
    if (cameraSelectDropdown) {
      cameraSelectDropdown.addEventListener('change', (e) => {
        focusCamera(e.target.value);
      });
    }

    // Modal open/close
    if (btnOpenCamManager) {
      btnOpenCamManager.addEventListener('click', () => {
        openModal();
      });
    }
    if (btnCloseCamManager) {
      btnCloseCamManager.addEventListener('click', closeModal);
    }
    if (modalCameraManager) {
      modalCameraManager.addEventListener('click', (e) => {
        if (e.target === modalCameraManager) closeModal();
      });
    }

    // Auto-Discovery scan
    if (btnScanDevices) {
      btnScanDevices.addEventListener('click', scanDevices);
    }

    // Preset & credential change -> update source URL
    [presetSelect, inputCamIp, inputCamPort, inputCamUser, inputCamPass, inputCamChannel, selectCamStream].forEach(elem => {
      if (elem) {
        elem.addEventListener('input', updatePresetUrl);
        elem.addEventListener('change', updatePresetUrl);
      }
    });

    // Test connection
    if (btnTestConnection) {
      btnTestConnection.addEventListener('click', testConnection);
    }

    // Form submit (Add / Save camera)
    if (camForm) {
      camForm.addEventListener('submit', saveCamera);
    }
  }

  function openModal() {
    modalCameraManager.style.display = 'flex';
    refreshCameras();
  }

  function closeModal() {
    modalCameraManager.style.display = 'none';
    resetForm();
  }

  function resetForm() {
    if (camForm) camForm.reset();
    inputCamId.readOnly = false;
    inputCamPort.value = '554';
    inputCamChannel.value = '1';
    testPreviewImg.src = '';
    testPreviewImg.style.display = 'none';
    testPreviewMeta.textContent = 'Click "Test Connection" to verify source.';
  }

  // Load Presets
  async function loadPresets() {
    try {
      const resp = await fetch('/api/cameras/presets');
      if (resp.ok) {
        cameraPresets = await resp.json();
        if (presetSelect) {
          presetSelect.innerHTML = cameraPresets.map(p => 
            `<option value="${p.id}">${p.name}</option>`
          ).join('');
        }
      }
    } catch (e) {
      console.warn('Could not load camera presets:', e);
    }
  }

  // Auto-build RTSP URL from inputs
  function updatePresetUrl() {
    const preset = presetSelect ? presetSelect.value : 'generic';
    const ip = (inputCamIp ? inputCamIp.value : '').trim();
    const port = (inputCamPort ? inputCamPort.value : '554').trim();
    const user = (inputCamUser ? inputCamUser.value : '').trim();
    const pass = (inputCamPass ? inputCamPass.value : '').trim();
    const channel = (inputCamChannel ? inputCamChannel.value : '1').trim() || '1';
    const stream = selectCamStream ? selectCamStream.value : 'main';

    if (!ip) return;

    const userEnc = user ? encodeURIComponent(user) : '';
    const passEnc = pass ? encodeURIComponent(pass) : '';
    let auth = '';
    if (userEnc && passEnc) auth = `${userEnc}:${passEnc}@`;
    else if (userEnc) auth = `${userEnc}@`;

    const netloc = (port && port !== '554') ? `${auth}${ip}:${port}` : `${auth}${ip}`;

    let generatedUrl = '';
    if (preset === 'hikvision') {
      const streamSuffix = (stream === 'main') ? '01' : '02';
      generatedUrl = `rtsp://${netloc}/Streaming/Channels/${channel}${streamSuffix}`;
    } else if (preset === 'tapo') {
      const streamPath = (stream === 'main') ? 'stream1' : 'stream2';
      generatedUrl = `rtsp://${netloc}/${streamPath}`;
    } else if (preset === 'ezviz') {
      const authEz = passEnc ? `admin:${passEnc}@` : auth;
      const netlocEz = (port && port !== '554') ? `${authEz}${ip}:${port}` : `${authEz}${ip}`;
      const suffix = (stream === 'main') ? 'main' : 'sub';
      generatedUrl = `rtsp://${netlocEz}/h264/ch${channel}/${suffix}`;
    } else if (preset === 'dahua') {
      const subtype = (stream === 'main') ? '0' : '1';
      generatedUrl = `rtsp://${netloc}/cam/realmonitor?channel=${channel}&subtype=${subtype}`;
    } else {
      generatedUrl = `rtsp://${netloc}/live`;
    }

    if (inputCamSource) {
      inputCamSource.value = generatedUrl;
    }
  }

  // Test Connection
  async function testConnection() {
    const source = (inputCamSource ? inputCamSource.value : '').trim();
    if (!source) {
      showToast('Please enter a source (RTSP URL, USB index, or video file) to test.', 'warning');
      return;
    }

    btnTestConnection.disabled = true;
    btnTestConnection.textContent = '⏳ Testing...';
    testPreviewMeta.textContent = 'Connecting to video source...';

    try {
      const resp = await fetch('/api/cameras/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: source })
      });
      const data = await resp.json();

      if (data.success) {
        testPreviewImg.src = `data:image/jpeg;base64,${data.snapshot_base64}`;
        testPreviewImg.style.display = 'block';
        testPreviewMeta.innerHTML = `<span style="color:#10b981;">✓ Connected</span> | ${data.resolution} @ ${data.fps} FPS`;
      } else {
        testPreviewImg.style.display = 'none';
        testPreviewMeta.innerHTML = `<span style="color:#ef4444;">✗ Connection Failed</span>: ${data.error || 'Unknown error'}`;
      }
    } catch (e) {
      testPreviewImg.style.display = 'none';
      testPreviewMeta.innerHTML = `<span style="color:#ef4444;">✗ Request Error</span>: ${e.message}`;
    } finally {
      btnTestConnection.disabled = false;
      btnTestConnection.textContent = '⚡ Test Connection';
    }
  }

  // Scan Devices
  async function scanDevices() {
    if (!btnScanDevices) return;
    btnScanDevices.disabled = true;
    btnScanDevices.textContent = '🔍 Scanning LAN & USB...';
    discoveredDevicesList.innerHTML = '<div class="empty-state">Probing hardware USB ports and LAN ONVIF broadcasts...</div>';

    try {
      const resp = await fetch('/api/cameras/discover');
      const devices = await resp.json();

      if (!devices || devices.length === 0) {
        discoveredDevicesList.innerHTML = '<div class="empty-state">No new cameras discovered. Ensure cameras are powered and on the same subnet.</div>';
        return;
      }

      discoveredDevicesList.innerHTML = devices.map(dev => `
        <div class="discovered-device-card glass-panel">
          <div class="dev-info">
            <div class="dev-title">${escapeHtml(dev.name)}</div>
            <div class="dev-sub">
              <span class="badge ${dev.type === 'usb' ? 'badge-usb' : 'badge-onvif'}">${dev.type.toUpperCase()}</span>
              <span>${escapeHtml(String(dev.source))}</span>
              ${dev.resolution ? `<span>${dev.resolution}</span>` : ''}
            </div>
          </div>
          <div class="dev-actions">
            <button class="btn btn-xs btn-outline btn-test-discovered" data-source="${escapeHtml(String(dev.source))}">Test</button>
            <button class="btn btn-xs btn-primary btn-add-discovered" 
              data-id="${escapeHtml(dev.id)}" 
              data-name="${escapeHtml(dev.name)}" 
              data-source="${escapeHtml(String(dev.source))}"
              data-type="${escapeHtml(dev.type)}">
              ➕ Add
            </button>
          </div>
        </div>
      `).join('');

      // Bind discovered actions
      discoveredDevicesList.querySelectorAll('.btn-test-discovered').forEach(btn => {
        btn.addEventListener('click', () => {
          inputCamSource.value = btn.getAttribute('data-source');
          testConnection();
        });
      });

      discoveredDevicesList.querySelectorAll('.btn-add-discovered').forEach(btn => {
        btn.addEventListener('click', () => {
          inputCamId.value = btn.getAttribute('data-id');
          inputCamName.value = btn.getAttribute('data-name');
          inputCamSource.value = btn.getAttribute('data-source');
          testConnection();
        });
      });

    } catch (e) {
      discoveredDevicesList.innerHTML = `<div class="empty-state" style="color:#ef4444;">Discovery error: ${e.message}</div>`;
    } finally {
      btnScanDevices.disabled = false;
      btnScanDevices.textContent = '🔍 Scan for Devices';
    }
  }

  // Refresh Cameras list
  async function refreshCameras() {
    try {
      const resp = await fetch('/api/cameras');
      if (resp.ok) {
        activeCameras = await resp.json();
        renderActiveCamerasTable();
        updateCameraDropdown();
        renderGrid();
      }
    } catch (e) {
      console.warn('Could not fetch active cameras:', e);
    }
  }

  function updateCameraDropdown() {
    if (!cameraSelectDropdown) return;
    cameraSelectDropdown.innerHTML = activeCameras.map(c => 
      `<option value="${c.id}" ${c.id === focusedCameraId ? 'selected' : ''}>${c.name} (${c.id})</option>`
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
          ${c.status.toUpperCase()} (${c.fps} FPS)
        </td>
        <td>
          <button class="btn btn-xs ${c.enabled ? 'btn-outline' : 'btn-primary'} btn-toggle-cam" data-id="${c.id}">
            ${c.enabled ? '⏸ Pause' : '▶ Enable'}
          </button>
        </td>
        <td>
          <button class="btn btn-xs btn-outline btn-focus-cam" data-id="${c.id}">🔍 Focus</button>
          <button class="btn btn-xs btn-danger btn-delete-cam" data-id="${c.id}">🗑️</button>
        </td>
      </tr>
    `).join('');

    // Table actions
    activeCamerasTableBody.querySelectorAll('.btn-toggle-cam').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        await fetch(`/api/cameras/${id}/toggle`, { method: 'POST' });
        await refreshCameras();
      });
    });

    activeCamerasTableBody.querySelectorAll('.btn-focus-cam').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        focusCamera(id);
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

  // Save or Add camera
  async function saveCamera(e) {
    e.preventDefault();
    const id = inputCamId.value.trim();
    const name = inputCamName.value.trim();
    const source = inputCamSource.value.trim();

    if (!id || !name || !source) {
      showToast('Please fill Camera ID, Name, and Video Source.', 'warning');
      return;
    }

    const payload = {
      id: id,
      name: name,
      source: source,
      type: presetSelect.value || 'rtsp',
      detector: document.getElementById('cam-detector-select')?.value || 'mock',
      tracker: document.getElementById('cam-tracker-select')?.value || 'centroid',
      enabled: true,
    };

    try {
      const resp = await fetch('/api/cameras', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (resp.ok) {
        showToast(`Camera '${name}' added successfully!`, 'success');
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

  // Focus single camera (1x1 mode)
  function focusCamera(cameraId) {
    focusedCameraId = cameraId;
    const cam = activeCameras.find(c => c.id === cameraId) || activeCameras[0];
    if (cam) {
      if (liveStreamImg) {
        liveStreamImg.src = `/stream/${cam.id}`;
      }
      if (streamTitle) {
        const fullTitle = `Camera Feed: ${cam.name.toUpperCase()} (${cam.id})`;
        streamTitle.textContent = fullTitle;
        streamTitle.title = fullTitle;
      }
      if (cameraSelectDropdown) {
        cameraSelectDropdown.value = cam.id;
      }
      if (window.App && typeof window.App.switchCamera === 'function') {
        window.App.switchCamera(cam.id);
      }
    }
    setGridMode('1x1');
  }

  // Set Multi-Camera Grid Mode (1x1, 2x2, 3x3)
  function setGridMode(mode) {
    currentGridMode = mode;

    document.querySelectorAll('.grid-switch-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-grid') === mode);
    });

    renderGrid();
  }

  function renderGrid() {
    if (!multiGridContainer || !singleVideoWrapper) return;

    if (currentGridMode === '1x1') {
      multiGridContainer.style.display = 'none';
      multiGridContainer.innerHTML = ''; // Detach background grid streams to enable hibernation
      singleVideoWrapper.style.display = 'flex';
      window.dispatchEvent(new Event('resize'));
    } else {
      singleVideoWrapper.style.display = 'none';
      multiGridContainer.style.display = 'grid';

      multiGridContainer.className = `multi-camera-grid grid-${currentGridMode}`;

      // Render camera tiles
      multiGridContainer.innerHTML = activeCameras.map(cam => `
        <div class="camera-grid-tile glass-panel ${cam.id === focusedCameraId ? 'focused-tile' : ''}" data-id="${cam.id}">
          <div class="tile-header">
            <span class="tile-title">${escapeHtml(cam.name)}</span>
            <span class="tile-status-badge ${cam.status === 'online' ? 'online' : 'offline'}">${cam.status.toUpperCase()}</span>
          </div>
          <div class="tile-video-container">
            <img src="/stream/${cam.id}" alt="${escapeHtml(cam.name)}" loading="lazy" />
          </div>
          <div class="tile-footer">
            <span class="tile-fps">${cam.fps} FPS</span>
            <span class="tile-tracks">${cam.active_tracks_count || 0} tracks</span>
            <button class="btn btn-xs btn-primary btn-tile-focus" data-id="${cam.id}">🔍 View 1x1</button>
          </div>
        </div>
      `).join('');

      // Add click to focus handlers
      multiGridContainer.querySelectorAll('.camera-grid-tile, .btn-tile-focus').forEach(elem => {
        elem.addEventListener('click', (e) => {
          const camId = elem.getAttribute('data-id');
          if (camId) {
            focusCamera(camId);
          }
        });
      });
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

  window.addEventListener('beforeunload', () => {
    if (multiGridContainer) multiGridContainer.innerHTML = '';
  });
  window.addEventListener('pagehide', () => {
    if (multiGridContainer) multiGridContainer.innerHTML = '';
  });

  // Export module to global window
  window.CameraManager = {
    init: init,
    refreshCameras: refreshCameras,
    focusCamera: focusCamera,
    setGridMode: setGridMode,
  };

  // Auto-init on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
