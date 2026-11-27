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

  function buildRtspUrl(preset, netloc, ip, port, auth, channel, stream) {
    if (preset === 'hikvision') {
      return `rtsp://${netloc}/Streaming/Channels/${channel}${stream === 'main' ? '01' : '02'}`;
    }
    if (preset === 'tapo') {
      return `rtsp://${netloc}/${stream === 'main' ? 'stream1' : 'stream2'}`;
    }
    if (preset === 'ezviz') {
      const authEz = auth.passEnc ? `admin:${auth.passEnc}@` : auth.prefix;
      const netlocEz = (port && port !== '554') ? `${authEz}${ip}:${port}` : `${authEz}${ip}`;
      return `rtsp://${netlocEz}/h264/ch${channel}/${stream === 'main' ? 'main' : 'sub'}`;
    }
    if (preset === 'dahua') {
      return `rtsp://${netloc}/cam/realmonitor?channel=${channel}&subtype=${stream === 'main' ? '0' : '1'}`;
    }
    return `rtsp://${netloc}/live`;
  }

  function updatePresetUrl() {
    const preset = document.getElementById('cam-preset-select')?.value || 'generic';
    const ip = (document.getElementById('cam-ip-input')?.value || '').trim();
    if (!ip) return;
    const port = (document.getElementById('cam-port-input')?.value || '554').trim();
    const user = (document.getElementById('cam-user-input')?.value || '').trim();
    const pass = (document.getElementById('cam-pass-input')?.value || '').trim();
    const channel = (document.getElementById('cam-channel-input')?.value || '1').trim() || '1';
    const stream = document.getElementById('cam-stream-select')?.value || 'main';
    const userEnc = user ? encodeURIComponent(user) : '';
    const passEnc = pass ? encodeURIComponent(pass) : '';
    const prefix = (userEnc && passEnc) ? `${userEnc}:${passEnc}@` : (userEnc ? `${userEnc}@` : '');
    const netloc = (port && port !== '554') ? `${prefix}${ip}:${port}` : `${prefix}${ip}`;
    const inputCamSource = document.getElementById('cam-source-input');
    if (inputCamSource) {
      inputCamSource.value = buildRtspUrl(preset, netloc, ip, port, { prefix, passEnc }, channel, stream);
    }
  }

  function renderTestPreview(data, errMsg = '') {
    const img = document.getElementById('test-preview-img');
    const meta = document.getElementById('test-preview-meta');
    if (data?.success) {
      if (img) {
        img.src = `data:image/jpeg;base64,${data.snapshot_base64}`;
        img.style.display = 'block';
      }
      if (meta) meta.innerHTML = `<span style="color:#10b981;">✓ Connected</span> | ${escapeHtml(data.resolution)} @ ${data.fps} FPS`;
      return;
    }
    if (img) img.style.display = 'none';
    if (meta) {
      const label = errMsg ? 'Request Error' : 'Connection Failed';
      const detail = errMsg || data?.error || 'Unknown error';
      meta.innerHTML = `<span style="color:#ef4444;">✗ ${label}</span>: ${escapeHtml(detail)}`;
    }
  }

  async function testConnection(deviceName = '') {
    const btnTest = document.getElementById('btn-test-connection');
    const meta = document.getElementById('test-preview-meta');
    const sourceInput = document.getElementById('cam-source-input');
    const source = (sourceInput?.value || '').trim();
    if (!source) {
      showToast('Please enter a source (RTSP URL, USB index, or video file) to test.', 'warning');
      return;
    }
    const resolvedDeviceName = (
      typeof deviceName === 'string' && deviceName.trim()
        ? deviceName.trim()
        : (sourceInput?.dataset?.deviceName || '').trim()
    );
    const payload = resolvedDeviceName ? { source, device_name: resolvedDeviceName } : { source };
    if (btnTest) { btnTest.disabled = true; btnTest.textContent = '⏳ Testing...'; }
    if (meta) meta.textContent = 'Connecting to video source...';
    try {
      const resp = await fetch('/api/cameras/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      renderTestPreview(await resp.json());
    } catch (e) {
      renderTestPreview(null, e.message);
    } finally {
      if (btnTest) { btnTest.disabled = false; btnTest.textContent = '⚡ Test Connection'; }
    }
  }

  function renderDiscoveredCards(devices) {
    return devices.map(dev => {
      const devName = dev.device_name || dev.details?.device_name || dev.name || '';
      const virtBadge = dev.details?.is_virtual
        ? '<span class="badge" style="background:rgba(99,102,241,0.2);color:#818cf8;border:1px solid #6366f1;">VIRTUAL</span>'
        : '';
      return `
        <div class="discovered-device-card glass-panel">
          <div class="dev-info">
            <div class="dev-title">${escapeHtml(dev.name)}</div>
            <div class="dev-sub">
              <span class="badge ${dev.type === 'usb' ? 'badge-usb' : 'badge-onvif'}">${escapeHtml((dev.type || 'rtsp').toUpperCase())}</span>
              ${virtBadge}<span>#${escapeHtml(String(dev.source))}</span>
              ${dev.resolution ? `<span>${escapeHtml(dev.resolution)}</span>` : ''}
              ${dev.fps ? `<span>${dev.fps} FPS</span>` : ''}
            </div>
          </div>
          <div class="dev-actions">
            <button class="btn btn-xs btn-outline btn-test-discovered" data-source="${escapeHtml(String(dev.source))}" data-device-name="${escapeHtml(devName)}">Test</button>
            <button class="btn btn-xs btn-primary btn-add-discovered"
              data-id="${escapeHtml(dev.id)}" data-name="${escapeHtml(dev.name)}"
              data-source="${escapeHtml(String(dev.source))}" data-type="${escapeHtml(dev.type || '')}"
              data-device-name="${escapeHtml(devName)}">➕ Add</button>
          </div>
        </div>`;
    }).join('');
  }

  function bindDiscoveredCardActions(listEl, onDeviceSelected) {
    listEl.querySelectorAll('.btn-test-discovered').forEach(btn => {
      btn.addEventListener('click', () => {
        const inputCamSource = document.getElementById('cam-source-input');
        const devName = btn.getAttribute('data-device-name') || '';
        if (inputCamSource) {
          inputCamSource.value = btn.getAttribute('data-source');
          if (inputCamSource.dataset) inputCamSource.dataset.deviceName = devName;
        }
        testConnection(devName);
      });
    });
    listEl.querySelectorAll('.btn-add-discovered').forEach(btn => {
      btn.addEventListener('click', () => {
        const selection = {
          id: btn.getAttribute('data-id'),
          name: btn.getAttribute('data-name'),
          source: btn.getAttribute('data-source'),
          type: btn.getAttribute('data-type') || undefined,
          device_name: btn.getAttribute('data-device-name') || btn.getAttribute('data-name'),
        };
        if (onDeviceSelected) { onDeviceSelected(selection); return; }
        const inputCamId = document.getElementById('cam-id-input');
        const inputCamName = document.getElementById('cam-name-input');
        const inputCamSource = document.getElementById('cam-source-input');
        if (inputCamId) inputCamId.value = selection.id;
        if (inputCamName) inputCamName.value = selection.name;
        if (inputCamSource) inputCamSource.value = selection.source;
        testConnection();
      });
    });
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
        listEl.innerHTML = '<div class="empty-state">No new cameras discovered. Ensure cameras are powered and on the same subnet. (Note: Inside Docker containers, USB webcams are isolated on the host; run on host via <code>python main.py</code> for direct USB access).</div>';
        return;
      }
      listEl.innerHTML = renderDiscoveredCards(devices);
      bindDiscoveredCardActions(listEl, onDeviceSelected);
    } catch (e) {
      listEl.innerHTML = `<div class="empty-state" style="color:#ef4444;">Discovery error: ${escapeHtml(e.message)}</div>`;
    } finally {
      btnScan.disabled = false;
      btnScan.textContent = '🔍 Scan for Devices';
    }
  }

  async function releaseCameras() {
    const btnRelease = document.getElementById('btn-release-cameras');
    if (btnRelease) {
      btnRelease.disabled = true;
      btnRelease.textContent = '⏳ Releasing...';
    }
    try {
      const resp = await fetch('/api/cameras/release', { method: 'POST' });
      const data = await resp.json();
      showToast(data.message || 'Camera handles released.', 'success');
      setTimeout(() => scanDevices(), 400);
    } catch (e) {
      showToast(`Failed to release: ${e.message}`, 'error');
    } finally {
      if (btnRelease) {
        btnRelease.disabled = false;
        btnRelease.textContent = '🔓 Release Blocked';
      }
    }
  }

  window.CameraDiscovery = {
    updatePresetUrl: updatePresetUrl,
    testConnection: testConnection,
    scanDevices: scanDevices,
    releaseCameras: releaseCameras,
  };
})();

