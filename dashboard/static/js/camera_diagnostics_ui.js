/**
 * Intelligent Tracker - Camera Diagnostics UI & Traceback Inspector.
 * Coordinates error banners, diagnostic modal presentation, lock releasing,
 * and direct 'Edit in Camera Manager' workflow transitions.
 */

(function () {
  'use strict';

  let currentDiagCameraId = null;

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

  function init() {
    bindEvents();
    // Intercept active camera updates to show/hide error overlays
    setInterval(checkActiveCameraHealth, 3000);
  }

  function bindDiagActionButton(btn, urlForCam, label, busyLabel, idleLabel, onSuccess) {
    if (!btn) return;
    btn.addEventListener('click', async () => {
      if (!currentDiagCameraId) return;
      btn.disabled = true;
      btn.textContent = busyLabel;
      try {
        const resp = await fetch(urlForCam(encodeURIComponent(currentDiagCameraId)), { method: 'POST' });
        const data = await resp.json();
        if (resp.ok) {
          onSuccess(data);
          await openDiagnosticModal(currentDiagCameraId);
        } else {
          showToast(`${label} failed: ${data.detail || 'Error'}`, 'warning');
        }
      } catch (e) {
        showToast(`Network error: ${e.message}`, 'danger');
      } finally {
        btn.disabled = false;
        btn.textContent = idleLabel;
      }
    });
  }

  function bindEvents() {
    const modalDiag = document.getElementById('modal-camera-diagnostics');
    document.getElementById('modal-diag-close')?.addEventListener('click', closeDiagnosticModal);
    document.getElementById('modal-diag-cancel')?.addEventListener('click', closeDiagnosticModal);
    modalDiag?.addEventListener('click', (e) => {
      if (e.target === modalDiag) closeDiagnosticModal();
    });
    document.getElementById('diag-btn-edit-manager')?.addEventListener('click', () => {
      const camId = currentDiagCameraId;
      closeDiagnosticModal();
      if (camId && window.CameraManager?.editCamera) window.CameraManager.editCamera(camId);
      else {
        const modalCam = document.getElementById('modal-camera-manager');
        if (modalCam) modalCam.style.display = 'flex';
      }
    });
    bindDiagActionButton(
      document.getElementById('diag-btn-release-lock'),
      (cid) => `/api/cameras/${cid}/release`,
      'release',
      '⏳ Releasing...',
      '🔓 Release Device Lock',
      (data) => showToast(`Camera lock released: ${data.release_result?.status || 'Done'}`, 'success')
    );
    bindDiagActionButton(
      document.getElementById('diag-btn-probe-channel'),
      (cid) => `/api/cameras/${cid}/probe`,
      'probe',
      '⏳ Probing...',
      '⚡ Probe Hardware',
      (data) => showToast(`Probe complete: Operational=${data.probe?.operational}`, data.probe?.operational ? 'success' : 'warning')
    );
  }

  function isLoadedCameraId(activeSelect, camId) {
    if (!camId) return false;
    const options = activeSelect?.options;
    if (options && typeof options.length === 'number') {
      return Array.from(options).some(opt => opt && opt.value === camId);
    }
    const inventory = window.CameraManager?.getActiveCameras?.();
    return Array.isArray(inventory) ? inventory.some(cam => cam && cam.id === camId) : false;
  }

  async function checkActiveCameraHealth() {
    const activeSelect = document.getElementById('active-camera-select');
    const camId = activeSelect ? activeSelect.value : '';
    if (!isLoadedCameraId(activeSelect, camId)) return;

    try {
      const resp = await fetch(`/api/cameras/${encodeURIComponent(camId)}/diagnostics`);
      if (!resp.ok) return;
      const data = await resp.json();

      updateLiveBanner(data);
    } catch (e) {
      // Ignore background network polling errors
    }
  }

  function updateLiveBanner(diag) {
    const videoWrapper = document.getElementById('video-wrapper');
    if (!videoWrapper) return;

    let banner = document.getElementById('active-camera-error-banner');
    if (diag.status === 'error') {
      if (!banner) {
        banner = document.createElement('div');
        banner.id = 'active-camera-error-banner';
        banner.className = 'camera-error-banner';
        videoWrapper.appendChild(banner);
      }
      banner.style.display = 'flex';
      banner.innerHTML = `
        <div class="camera-error-banner-text">
          <span class="camera-error-banner-title">⚠️ Camera Issue: ${escapeHtml(diag.error_code || 'Stream Offline')}</span>
          <span class="camera-error-banner-msg" title="${escapeHtml(diag.last_error || '')}">
            ${escapeHtml(diag.last_error || 'No frames received from video source.')}
          </span>
        </div>
        <div class="camera-error-banner-actions">
          <button class="btn btn-xs btn-outline" id="btn-banner-diagnose" style="color: #f87171; border-color: rgba(239, 68, 68, 0.5);">
            🛠️ Diagnose
          </button>
        </div>
      `;
      const btnDiag = banner.querySelector('#btn-banner-diagnose');
      if (btnDiag) {
        btnDiag.addEventListener('click', () => openDiagnosticModal(diag.camera_id));
      }
    } else if (banner) {
      banner.style.display = 'none';
    }
  }

  function renderDiagDetails(data) {
    const titleEl = document.getElementById('diag-modal-title');
    const statStatus = document.getElementById('diag-stat-status');
    const statCode = document.getElementById('diag-stat-code');
    const statSource = document.getElementById('diag-stat-source');
    const statDevice = document.getElementById('diag-stat-device');
    const statFailures = document.getElementById('diag-stat-failures');
    const adviceBody = document.getElementById('diag-advice-body');
    const traceBox = document.getElementById('diag-traceback-box');
    if (titleEl) titleEl.textContent = `Camera Diagnostics: ${data.name || data.camera_id} (${data.camera_id})`;
    if (statStatus) {
      statStatus.textContent = (data.status || 'unknown').toUpperCase();
      statStatus.className = `diag-stat-value status-${data.status === 'online' ? 'online' : 'error'}`;
    }
    if (statCode) statCode.textContent = data.error_code || 'OK';
    if (statSource) statSource.textContent = data.source || '-';
    if (statDevice) statDevice.textContent = data.device_name || 'Generic / Unbound';
    if (statFailures) statFailures.textContent = String(data.failure_count || 0);
    if (adviceBody) adviceBody.textContent = data.suggested_action || 'System running normally.';
    if (traceBox) {
      const details = [];
      if (data.last_error) details.push(`ERROR MESSAGE:\n${data.last_error}`);
      if (data.attempted_paths?.length) details.push(`\nATTEMPTED FILE PATHS:\n${data.attempted_paths.join('\n')}`);
      if (data.diagnostics && Object.keys(data.diagnostics).length) {
        details.push(`\nHARDWARE PROBE DETAILS:\n${JSON.stringify(data.diagnostics, null, 2)}`);
      }
      if (data.traceback) details.push(`\nTRACEBACK:\n${data.traceback}`);
      traceBox.textContent = details.length ? details.join('\n') : 'No active errors or tracebacks reported.';
    }
  }

  async function openDiagnosticModal(cameraId) {
    currentDiagCameraId = cameraId;
    const modal = document.getElementById('modal-camera-diagnostics');
    if (!modal) return;
    modal.style.display = 'flex';
    const titleEl = document.getElementById('diag-modal-title');
    const statStatus = document.getElementById('diag-stat-status');
    const adviceBody = document.getElementById('diag-advice-body');
    if (titleEl) titleEl.textContent = `Camera Diagnostics: ${cameraId}`;
    if (statStatus) { statStatus.textContent = 'Loading...'; statStatus.className = 'diag-stat-value'; }
    try {
      const resp = await fetch(`/api/cameras/${encodeURIComponent(cameraId)}/diagnostics`);
      if (!resp.ok) throw new Error('Could not fetch diagnostics');
      renderDiagDetails(await resp.json());
    } catch (e) {
      if (statStatus) statStatus.textContent = 'ERROR';
      if (adviceBody) adviceBody.textContent = e.message;
    }
  }

  function closeDiagnosticModal() {
    const modal = document.getElementById('modal-camera-diagnostics');
    if (modal) modal.style.display = 'none';
  }

  // Export on window
  window.CameraDiagnosticsUI = {
    init: init,
    openDiagnosticModal: openDiagnosticModal,
    closeDiagnosticModal: closeDiagnosticModal,
    checkActiveCameraHealth: checkActiveCameraHealth,
  };

  document.addEventListener('DOMContentLoaded', init);
})();

