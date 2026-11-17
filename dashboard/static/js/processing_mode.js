/**
 * Intelligent Tracker - Top-Bar Processing Mode UI & Visibility Auto-Sync.
 * Manages #processing-mode-select, localStorage persistence, deferred job badge,
 * and synchronization with GET/POST /api/system/processing-mode.
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'it_processing_mode';
  const CAM_STORAGE_KEY = 'it_focused_camera_id';
  const API_URL = '/api/system/processing-mode';
  const VALID_MODES = ['focus_only', 'full_realtime', 'capture_only', 'paused'];

  function readStorage(key) {
    try { return window.localStorage?.getItem(key) || null; } catch (_) { return null; }
  }

  function writeStorage(key, val) {
    try { if (val) window.localStorage?.setItem(key, val); } catch (err) { console.debug('localStorage write skipped:', err); }
  }

  const state = {
    mode: 'focus_only',
    focusedCameraId: readStorage(CAM_STORAGE_KEY),
    activeTab: 'live',
    deferredCount: 0,
    initialized: false,
  };

  function getEffectiveActiveTab() {
    return (typeof document !== 'undefined' && document.hidden) ? 'hidden' : (state.activeTab || 'live');
  }

  function readStoredMode() {
    const val = readStorage(STORAGE_KEY);
    return VALID_MODES.includes(val) ? val : null;
  }

  function writeStoredMode(mode) {
    if (VALID_MODES.includes(mode)) writeStorage(STORAGE_KEY, mode);
  }

  function normalizeTabName(tabId) {
    if (!tabId || typeof tabId !== 'string') return 'live';
    const cleaned = tabId.trim().replace(/^tab-/, '');
    return cleaned || 'live';
  }

  function renderUI() {
    const select = document.getElementById('processing-mode-select');
    const dot = document.getElementById('processing-mode-dot');
    const badge = document.getElementById('processing-mode-deferred-badge');

    if (select && select.value !== state.mode) {
      select.value = state.mode;
    }
    if (dot) {
      dot.className = `processing-mode-dot mode-${state.mode}`;
    }
    if (badge) {
      const count = Math.max(0, Number(state.deferredCount) || 0);
      badge.textContent = String(count);
      badge.classList.toggle('is-hidden', count === 0);
      badge.title = count > 0 ? `${count} deferred video indexing job(s) queued` : 'No deferred indexing jobs';
    }
    const pausedOverlay = document.getElementById('live-paused-overlay');
    if (pausedOverlay) pausedOverlay.hidden = state.mode !== 'paused';
  }

  let serverFocusedCameraId = null;

  function applyServerState(data) {
    if (!data || typeof data !== 'object') return;
    if (VALID_MODES.includes(data.mode)) { state.mode = data.mode; writeStoredMode(data.mode); }
    serverFocusedCameraId = (typeof data.focused_camera_id === 'string' && data.focused_camera_id) ? data.focused_camera_id : null;
    if (serverFocusedCameraId && isValidCameraId(serverFocusedCameraId)) state.focusedCameraId = serverFocusedCameraId;
    if (typeof data.active_tab === 'string' && data.active_tab && data.active_tab !== 'hidden') state.activeTab = data.active_tab;
    if (Array.isArray(data.deferred_jobs)) state.deferredCount = data.deferred_jobs.length;
    renderUI();
  }

  async function fetchStatus() {
    if (typeof fetch !== 'function') return null;
    try {
      const resp = await fetch(API_URL, { method: 'GET' });
      if (!resp || !resp.ok) return null;
      const data = await resp.json();
      applyServerState(data);
      if (data?.active_tab === 'hidden' && typeof document !== 'undefined' && !document.hidden) syncVisibility();
      return data;
    } catch (_) {
      return null;
    }
  }

  async function postModeUpdate(payload) {
    if (typeof fetch !== 'function') return null;
    try {
      const resp = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {}),
      });
      if (!resp || !resp.ok) return null;
      const data = await resp.json();
      applyServerState(data);
      return data;
    } catch (_) {
      return null;
    }
  }

  function setMode(mode) {
    if (!VALID_MODES.includes(mode)) return Promise.resolve(null);
    state.mode = mode;
    writeStoredMode(mode);
    renderUI();
    const payload = !document?.hidden ? { mode, active_tab: getEffectiveActiveTab() } : { mode };
    return postModeUpdate(payload).then(res => {
      if (mode !== 'paused' && state.activeTab === 'live' && !window.LivePlayer?.isPaused?.()) {
        window.LivePlayer?.attachLiveStream?.(document.getElementById('live-stream-img'), window.App?.getActiveCameraId?.(), true);
      }
      return res;
    });
  }

  function syncTabChange(tabId) {
    state.activeTab = normalizeTabName(tabId);
    return postModeUpdate({ active_tab: getEffectiveActiveTab() });
  }

  let availableCameras = null;

  function setAvailableCameras(ids) {
    if (!Array.isArray(ids)) return;
    availableCameras = new Set(ids.filter(id => typeof id === 'string' && id.trim()).map(id => id.trim()));
    if (state.focusedCameraId && !availableCameras.has(state.focusedCameraId)) state.focusedCameraId = null;
    if (!state.focusedCameraId && serverFocusedCameraId && availableCameras.has(serverFocusedCameraId)) {
      state.focusedCameraId = serverFocusedCameraId; writeStorage(CAM_STORAGE_KEY, serverFocusedCameraId);
    }
    const appCam = window.App?.getActiveCameraId?.();
    const reconcileId = state.focusedCameraId || (availableCameras.has(appCam) ? appCam : null);
    if (state.initialized && reconcileId && !serverFocusedCameraId) syncCameraFocus(reconcileId);
  }

  function isValidCameraId(id) {
    if (!id || typeof id !== 'string' || !id.trim()) return false;
    return availableCameras instanceof Set && availableCameras.has(id.trim());
  }

  function syncCameraFocus(cameraId) {
    if (!isValidCameraId(cameraId)) return Promise.resolve(null);
    const trimmed = cameraId.trim();
    const effectiveTab = getEffectiveActiveTab();
    state.focusedCameraId = trimmed;
    writeStorage(CAM_STORAGE_KEY, trimmed);
    const payload = effectiveTab !== 'hidden'
      ? { focused_camera_id: trimmed, active_tab: effectiveTab }
      : { focused_camera_id: trimmed };
    return postModeUpdate(payload);
  }

  function syncVisibility() {
    return postModeUpdate({ active_tab: getEffectiveActiveTab() });
  }

  function bindEvents() {
    const bindOnce = (id, ev, fn) => {
      const el = document.getElementById(id);
      if (el && !el.dataset.pmBound) { el.dataset.pmBound = '1'; el.addEventListener(ev, fn); return el; }
      return null;
    };
    bindOnce('processing-mode-select', 'change', (e) => setMode(e.target.value));
    bindOnce('btn-resume-processing-mode', 'click', () => setMode('focus_only'));
    const camSel = bindOnce('active-camera-select', 'change', (e) => syncCameraFocus(e.target.value));
    if (camSel?.value && isValidCameraId(camSel.value)) state.focusedCameraId = camSel.value;

    if (!state.initialized) {
      window.addEventListener('tab-changed', (e) => { if (e?.detail?.activeTab) syncTabChange(e.detail.activeTab); });
      document.addEventListener('visibilitychange', () => { syncVisibility(); });
      window.addEventListener('focus', () => { if (typeof document === 'undefined' || !document.hidden) syncVisibility(); });
    }
  }

  function init() {
    bindEvents();
    const savedMode = readStoredMode();
    if (savedMode) {
      state.mode = savedMode;
      renderUI();
      state.initialized = true;
      const payload = { mode: savedMode, active_tab: getEffectiveActiveTab() };
      if (state.focusedCameraId && isValidCameraId(state.focusedCameraId)) payload.focused_camera_id = state.focusedCameraId;
      return postModeUpdate(payload);
    }
    state.initialized = true;
    renderUI();
    return fetchStatus();
  }

  window.ProcessingModeUI = {
    STORAGE_KEY, VALID_MODES, init, setMode, setAvailableCameras,
    syncTabChange, syncCameraFocus, syncVisibility, refresh: fetchStatus, getState: () => ({ ...state }),
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init());
  } else {
    init();
  }
})();
