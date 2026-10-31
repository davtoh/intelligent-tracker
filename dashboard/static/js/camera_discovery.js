/**
 * Intelligent Tracker - Camera Auto-Discovery & RTSP Probe Submodule.
 * Handles LAN ONVIF broadcasts, USB device scanning, and connection pre-checks.
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

  function showToast(message, type = 'info') {
    if (typeof window.showToast === 'function') {
      window.showToast(message, type);
    } else {
      alert(message);
    }
  }

  function updatePresetUrl() {
    const presetSelect = document.getElementById('cam-preset-select');
    const inputCamIp = document.getElementById('cam-ip-input');
    const inputCamPort = document.getElementById('cam-port-input');
    const inputCamUser = document.getElementById('cam-user-input');
    const inputCamPass = document.getElementById('cam-pass-input');
    const inputCamChannel = document.getElementById('cam-channel-input');
    const selectCamStream = document.getElementById('cam-stream-select');
    const inputCamSource = document.getElementById('cam-source-input');

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

  async function testConnection() {
    const inputCamSource = document.getElementById('cam-source-input');
    const btnTest = document.getElementById('btn-test-connection');
    const testPreviewImg = document.getElementById('test-preview-img');
    const testPreviewMeta = document.getElementById('test-preview-meta');

    const source = (inputCamSource ? inputCamSource.value : '').trim();
    if (!source) {
      showToast('Please enter a source (RTSP URL, USB index, or video file) to test.', 'warning');
      return;
    }

    if (btnTest) {
      btnTest.disabled = true;
      btnTest.textContent = '⏳ Testing...';
    }
    if (testPreviewMeta) testPreviewMeta.textContent = 'Connecting to video source...';

    try {
      const resp = await fetch('/api/cameras/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: source })
      });
      const data = await resp.json();

      if (data.success) {
        if (testPreviewImg) {
          testPreviewImg.src = `data:image/jpeg;base64,${data.snapshot_base64}`;
          testPreviewImg.style.display = 'block';
        }
        if (testPreviewMeta) {
          testPreviewMeta.innerHTML = `<span style="color:#10b981;">✓ Connected</span> | ${escapeHtml(data.resolution)} @ ${data.fps} FPS`;
        }
      } else {
        if (testPreviewImg) testPreviewImg.style.display = 'none';
        if (testPreviewMeta) {
          testPreviewMeta.innerHTML = `<span style="color:#ef4444;">✗ Connection Failed</span>: ${escapeHtml(data.error || 'Unknown error')}`;
        }
      }
    } catch (e) {
      if (testPreviewImg) testPreviewImg.style.display = 'none';
      if (testPreviewMeta) {
        testPreviewMeta.innerHTML = `<span style="color:#ef4444;">✗ Request Error</span>: ${escapeHtml(e.message)}`;
      }
    } finally {
      if (btnTest) {
        btnTest.disabled = false;
        btnTest.textContent = '⚡ Test Connection';
      }
    }
  }

  async function scanDevices(onDeviceSelected) {
    const btnScan = document.getElementById('btn-scan-devices');
    const listEl = document.getElementById('discovered-devices-list');
    if (!btnScan || !listEl) return;

    btnScan.disabled = true;
    btnScan.textContent = '🔍 Scanning LAN & USB...';
    listEl.innerHTML = '<div class="empty-state">Probing hardware USB ports and LAN ONVIF broadcasts...</div>';

    try {
      const resp = await fetch('/api/cameras/discover');
      const devices = await resp.json();

      if (!devices || devices.length === 0) {
        listEl.innerHTML = '<div class="empty-state">No new cameras discovered. Ensure cameras are powered and on the same subnet.</div>';
        return;
      }

      listEl.innerHTML = devices.map(dev => `
        <div class="discovered-device-card glass-panel">
          <div class="dev-info">
            <div class="dev-title">${escapeHtml(dev.name)}</div>
            <div class="dev-sub">
              <span class="badge ${dev.type === 'usb' ? 'badge-usb' : 'badge-onvif'}">${escapeHtml(dev.type.toUpperCase())}</span>
              <span>${escapeHtml(String(dev.source))}</span>
              ${dev.resolution ? `<span>${escapeHtml(dev.resolution)}</span>` : ''}
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

      listEl.querySelectorAll('.btn-test-discovered').forEach(btn => {
        btn.addEventListener('click', () => {
          const inputCamSource = document.getElementById('cam-source-input');
          if (inputCamSource) inputCamSource.value = btn.getAttribute('data-source');
          testConnection();
        });
      });

      listEl.querySelectorAll('.btn-add-discovered').forEach(btn => {
        btn.addEventListener('click', () => {
          const id = btn.getAttribute('data-id');
          const name = btn.getAttribute('data-name');
          const source = btn.getAttribute('data-source');
          if (onDeviceSelected) {
            onDeviceSelected({ id, name, source });
          } else {
            const inputCamId = document.getElementById('cam-id-input');
            const inputCamName = document.getElementById('cam-name-input');
            const inputCamSource = document.getElementById('cam-source-input');
            if (inputCamId) inputCamId.value = id;
            if (inputCamName) inputCamName.value = name;
            if (inputCamSource) inputCamSource.value = source;
            testConnection();
          }
        });
      });

    } catch (e) {
      listEl.innerHTML = `<div class="empty-state" style="color:#ef4444;">Discovery error: ${escapeHtml(e.message)}</div>`;
    } finally {
      btnScan.disabled = false;
      btnScan.textContent = '🔍 Scan for Devices';
    }
  }

  window.CameraDiscovery = {
    updatePresetUrl: updatePresetUrl,
    testConnection: testConnection,
    scanDevices: scanDevices,
  };
})();

