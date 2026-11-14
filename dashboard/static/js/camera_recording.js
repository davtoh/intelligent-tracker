/**
 * Intelligent Tracker - Live Camera MP4 Recording UI Controller.
 * Syncs per-camera recording state, options, multi-grid controls, and Video Studio handoff.
 */

(function () {
  'use strict';

  const recordingByCamera = new Map();
  const notifiedCompletions = new Set();
  let pollTimer = null;

  function getActiveCameraId() {
    const select = document.getElementById('active-camera-select');
    const appCam = window.App?.getActiveCameraId?.();
    if (select && select.options && select.options.length > 0) {
      const opts = Array.from(select.options);
      if (appCam && opts.some(opt => opt.value === appCam)) return appCam;
      if (select.value) return select.value;
    }
    const barCam = document.getElementById('camera-recording-bar')?.getAttribute('data-camera-id');
    return appCam || select?.value || barCam || 'cam_01';
  }

  function formatBytes(bytes) {
    const size = Math.max(0, Number(bytes) || 0);
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(2)} MB`;
    return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function formatElapsed(seconds) {
    const sec = Math.max(0, Number(seconds) || 0);
    const mins = Math.floor(sec / 60);
    const rem = (sec % 60).toFixed(1).padStart(4, '0');
    return `${String(mins).padStart(2, '0')}:${rem}`;
  }

  function normalizeStatus(raw, fallbackCamId) {
    const src = raw && typeof raw === 'object' ? raw : {};
    const isRec = Boolean(src.is_recording);
    return {
      camera_id: src.camera_id || fallbackCamId || getActiveCameraId(),
      is_recording: isRec,
      status: src.status || (isRec ? 'recording' : 'idle'),
      recording_id: src.recording_id || null,
      filename: src.filename || '',
      frames_written: Number(src.frames_written || 0),
      elapsed_s: Number(src.elapsed_s || 0),
      size_bytes: Number(src.size_bytes || 0),
    };
  }

  function readRecordingOptions() {
    const payload = {};
    const filenameVal = (document.getElementById('rec-filename-input')?.value || '').trim();
    const fpsVal = parseFloat(document.getElementById('rec-fps-input')?.value || '');
    const durVal = parseFloat(document.getElementById('rec-max-duration-input')?.value || '');
    const framesVal = parseInt(document.getElementById('rec-max-frames-input')?.value || '', 10);
    const annotatedEl = document.getElementById('rec-annotated-toggle');
    if (filenameVal) payload.filename = filenameVal;
    if (Number.isFinite(fpsVal) && fpsVal > 0) payload.fps = fpsVal;
    if (Number.isFinite(durVal) && durVal > 0) payload.max_duration_s = durVal;
    if (Number.isFinite(framesVal) && framesVal > 0) payload.max_frames = framesVal;
    payload.annotated = annotatedEl ? Boolean(annotatedEl.checked) : true;
    return payload;
  }

  function updateTileRecordingState(status) {
    const tiles = document.querySelectorAll('.camera-grid-tile');
    tiles.forEach(tile => {
      if (tile.getAttribute('data-id') !== status.camera_id) return;
      const btn = tile.querySelector('.btn-tile-record');
      const badge = tile.querySelector('.tile-rec-badge');
      if (btn) {
        btn.classList?.toggle('recording', status.is_recording);
        btn.textContent = status.is_recording ? '⏹ Stop' : '⏺ Rec';
      }
      if (badge) {
        badge.hidden = !status.is_recording;
      }
    });
  }

  function renderActiveBar(status) {
    const bar = document.getElementById('camera-recording-bar');
    if (!bar) return;
    bar.setAttribute('data-camera-id', status.camera_id);
    const camBadge = document.getElementById('rec-camera-badge');
    const pill = document.getElementById('rec-status-pill');
    const statusText = document.getElementById('rec-status-text');
    const elapsedEl = document.getElementById('rec-elapsed-val');
    const framesEl = document.getElementById('rec-frames-val');
    const bytesEl = document.getElementById('rec-bytes-val');
    const fileEl = document.getElementById('rec-filename-val');
    const startBtn = document.getElementById('btn-record-start');
    const stopBtn = document.getElementById('btn-record-stop');
    const studioBtn = document.getElementById('btn-record-open-studio');
    if (camBadge) camBadge.textContent = String(status.camera_id).toUpperCase();
    if (pill) pill.className = `rec-status-pill ${status.status}`;
    if (statusText) statusText.textContent = String(status.status).toUpperCase();
    if (elapsedEl) elapsedEl.textContent = formatElapsed(status.elapsed_s);
    if (framesEl) framesEl.textContent = `${status.frames_written} frames`;
    if (bytesEl) bytesEl.textContent = formatBytes(status.size_bytes);
    if (fileEl) {
      fileEl.textContent = status.filename || '—';
      fileEl.title = status.filename || 'Output MP4 Filename';
    }
    if (startBtn) startBtn.disabled = status.is_recording;
    if (stopBtn) stopBtn.disabled = !status.is_recording;
    if (studioBtn) {
      const hasClip = Boolean(status.filename && !status.is_recording);
      studioBtn.style.display = hasClip ? 'inline-flex' : 'none';
      studioBtn.setAttribute('data-filename', status.filename || '');
    }
  }

  function openInVideoStudio(filename) {
    if (!filename) return;
    window.switchTab?.('tab-videos');
    const loadPromise = window.VideoScrubber?.loadVideosList?.();
    const selectClip = () => window.dispatchEvent(new CustomEvent('video-select-request', { detail: { filename } }));
    if (loadPromise && typeof loadPromise.then === 'function') {
      loadPromise.then(selectClip).catch(() => selectClip());
    } else {
      selectClip();
    }
  }

  function handleRecordingFinished(status) {
    if (!status.filename) return;
    const key = `${status.camera_id}:${status.recording_id || status.filename}`;
    if (notifiedCompletions.has(key)) return;
    notifiedCompletions.add(key);
    window.VideoScrubber?.loadVideosList?.();
    window.showToast?.(
      'Recording Saved',
      `${status.filename} (${formatBytes(status.size_bytes)})`,
      'success',
      'Open in Video Studio',
      () => openInVideoStudio(status.filename)
    );
  }

  function pollActiveRecordings() {
    const targets = new Set([getActiveCameraId()]);
    recordingByCamera.forEach((st, id) => {
      if (st && st.is_recording) targets.add(id);
    });
    targets.forEach(id => syncStatus(id));
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function syncPolling() {
    const anyActive = Array.from(recordingByCamera.values()).some(s => s.is_recording);
    if (anyActive && !pollTimer) {
      pollTimer = setInterval(pollActiveRecordings, 1500);
    } else if (!anyActive) {
      stopPolling();
    }
  }

  function applyStatusToDom(rawStatus) {
    if (!rawStatus || !rawStatus.camera_id) return null;
    const status = normalizeStatus(rawStatus, rawStatus.camera_id);
    const prev = recordingByCamera.get(status.camera_id);
    const justDone = Boolean(prev && prev.is_recording && !status.is_recording && (status.status === 'completed' || status.status === 'stopped'));
    recordingByCamera.set(status.camera_id, status);
    updateTileRecordingState(status);
    syncPolling();
    if (justDone) handleRecordingFinished(status);
    if (status.camera_id !== getActiveCameraId()) return status;
    renderActiveBar(status);
    return status;
  }

  async function syncStatus(cameraId) {
    const camId = cameraId || getActiveCameraId();
    if (!camId) return null;
    try {
      const resp = await fetch(`/api/cameras/${encodeURIComponent(camId)}/record/status`);
      if (!resp.ok) return null;
      const data = await resp.json();
      return applyStatusToDom(data);
    } catch (err) {
      console.debug('[CameraRecording] Status sync failed:', err);
      return null;
    }
  }

  async function startRecording(cameraId, overrideOpts) {
    const camId = cameraId || getActiveCameraId();
    const startBtn = document.getElementById('btn-record-start');
    if (startBtn && camId === getActiveCameraId()) startBtn.disabled = true;
    try {
      const body = overrideOpts || readRecordingOptions();
      const resp = await fetch(`/api/cameras/${encodeURIComponent(camId)}/record/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        window.showToast?.('Recording Error', data.detail || 'Failed to start MP4 recording.', 'error');
        await syncStatus(camId);
        return null;
      }
      const status = applyStatusToDom(data);
      window.showToast?.('Recording Started', `Recording ${status?.filename || camId}`, 'success');
      return status;
    } catch (err) {
      window.showToast?.('Recording Error', err.message || 'Network error.', 'error');
      renderActiveBar(recordingByCamera.get(getActiveCameraId()) || normalizeStatus({}, getActiveCameraId()));
      return null;
    }
  }

  async function stopRecording(cameraId) {
    const camId = cameraId || getActiveCameraId();
    const stopBtn = document.getElementById('btn-record-stop');
    if (stopBtn && camId === getActiveCameraId()) stopBtn.disabled = true;
    try {
      const resp = await fetch(`/api/cameras/${encodeURIComponent(camId)}/record/stop`, { method: 'POST' });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        window.showToast?.('Stop Recording Error', data.detail || 'No active recording.', 'warning');
        await syncStatus(camId);
        return null;
      }
      const status = applyStatusToDom(data);
      if (status) handleRecordingFinished(status);
      return status;
    } catch (err) {
      window.showToast?.('Stop Recording Error', err.message || 'Network error.', 'error');
      renderActiveBar(recordingByCamera.get(getActiveCameraId()) || normalizeStatus({}, getActiveCameraId()));
      return null;
    }
  }

  function toggleCameraRecording(cameraId) {
    const camId = cameraId || getActiveCameraId();
    const cached = recordingByCamera.get(camId);
    if (cached && cached.is_recording) return stopRecording(camId);
    return startRecording(camId, {});
  }

  function hydrateFromCameraList(cameras) {
    (cameras || []).forEach(cam => {
      if (!cam || !cam.id) return;
      const rec = cam.recording ? normalizeStatus(cam.recording, cam.id) : normalizeStatus({}, cam.id);
      recordingByCamera.set(cam.id, rec);
      updateTileRecordingState(rec);
    });
    const activeCamId = getActiveCameraId();
    renderActiveBar(recordingByCamera.get(activeCamId) || normalizeStatus({}, activeCamId));
    syncPolling();
  }

  function onTelemetryUpdate(recStatus, telemetryCamId) {
    if (!recStatus) return;
    if (telemetryCamId && recStatus.camera_id && telemetryCamId !== recStatus.camera_id) return;
    const payload = recStatus.camera_id ? recStatus : Object.assign({}, recStatus, { camera_id: telemetryCamId });
    applyStatusToDom(payload);
  }

  function onCameraFocused(cameraId) {
    const camId = cameraId || getActiveCameraId();
    const bar = document.getElementById('camera-recording-bar');
    if (bar) bar.setAttribute('data-camera-id', camId);
    renderActiveBar(recordingByCamera.get(camId) || normalizeStatus({}, camId));
    return syncStatus(camId);
  }

  function toggleOptionsPanel() {
    const panel = document.getElementById('rec-options-panel');
    const toggleBtn = document.getElementById('btn-record-options-toggle');
    if (!panel || !toggleBtn) return;
    const nextHidden = !panel.hidden;
    panel.hidden = nextHidden;
    toggleBtn.setAttribute('aria-expanded', String(!nextHidden));
  }

  function bindEvents() {
    document.getElementById('btn-record-start')?.addEventListener('click', () => startRecording());
    document.getElementById('btn-record-stop')?.addEventListener('click', () => stopRecording());
    document.getElementById('btn-record-options-toggle')?.addEventListener('click', toggleOptionsPanel);
    document.getElementById('btn-record-open-studio')?.addEventListener('click', (e) => {
      const fname = e.currentTarget?.getAttribute('data-filename');
      if (fname) openInVideoStudio(fname);
    });
    document.getElementById('active-camera-select')?.addEventListener('change', (e) => onCameraFocused(e.target.value));
    document.querySelectorAll('.nav-tab, .drawer-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        if (tab.getAttribute('data-tab') === 'tab-live') syncStatus(getActiveCameraId());
      });
    });
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) syncStatus(getActiveCameraId());
    });
    window.addEventListener('pagehide', stopPolling);
    window.addEventListener('beforeunload', stopPolling);
  }

  function init() {
    bindEvents();
    syncStatus(getActiveCameraId());
  }

  window.CameraRecording = {
    init: init,
    getActiveCameraId: getActiveCameraId,
    startRecording: startRecording,
    stopRecording: stopRecording,
    stopPolling: stopPolling,
    toggleCameraRecording: toggleCameraRecording,
    syncStatus: syncStatus,
    applyStatusToDom: applyStatusToDom,
    hydrateFromCameraList: hydrateFromCameraList,
    onTelemetryUpdate: onTelemetryUpdate,
    onCameraFocused: onCameraFocused,
    openInVideoStudio: openInVideoStudio,
    getCachedStatus: (camId) => recordingByCamera.get(camId) || null,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
