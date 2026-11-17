/**
 * Intelligent Tracker - Top-Bar Processing Mode UI & Visibility Auto-Sync.
 * Manages #processing-mode-select, localStorage persistence, deferred job badge,
 * and synchronization with GET/POST /api/system/processing-mode.
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'it_processing_mode';
  const API_URL = '/api/system/processing-mode';
  const VALID_MODES = ['focus_only', 'full_realtime', 'capture_only', 'paused'];

  const state = {
    mode: 'focus_only',
    focusedCameraId: 'cam_01',
    activeTab: 'live',
    deferredCount: 0,
    initialized: false,
  };

  function getEffectiveActiveTab() {
    return (typeof document !== 'undefined' && document.hidden) ? 'hidden' : (state.activeTab || 'live');
  }

  function readStoredMode() {
    try {
      const val = window.localStorage?.getItem(STORAGE_KEY);
      return VALID_MODES.includes(val) ? val : null;
    } catch (_) {
      return null;
    }
  }

  function writeStoredMode(mode) {
    try {
      if (VALID_MODES.includes(mode)) {
        window.localStorage?.setItem(STORAGE_KEY, mode);
      }
    } catch (_) {
      // Ignore storage quota / privacy mode errors
    }
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

  function applyServerState(data) {
    if (!data || typeof data !== 'object') return;
    if (VALID_MODES.includes(data.mode)) {
      state.mode = data.mode;
      writeStoredMode(data.mode);
    }
    if (typeof data.focused_camera_id === 'string' && data.focused_camera_id) state.focusedCameraId = data.focused_camera_id;
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

  function syncCameraFocus(cameraId) {
    if (!cameraId || typeof cameraId !== 'string') return Promise.resolve(null);
    const trimmed = cameraId.trim();
    if (!trimmed) return Promise.resolve(null);
    const effectiveTab = getEffectiveActiveTab();
    state.focusedCameraId = trimmed;
    const payload = effectiveTab !== 'hidden'
      ? { focused_camera_id: trimmed, active_tab: effectiveTab }
      : { focused_camera_id: trimmed };
    return postModeUpdate(payload);
  }

  function syncVisibility() {
    return postModeUpdate({ active_tab: getEffectiveActiveTab() });
  }

  function bindEvents() {
    const select = document.getElementById('processing-mode-select');
    if (select && !select.dataset.pmBound) {
      select.dataset.pmBound = '1';
      select.addEventListener('change', (e) => setMode(e.target.value));
    }

    const resumeBtn = document.getElementById('btn-resume-processing-mode');
    if (resumeBtn && !resumeBtn.dataset.pmBound) {
      resumeBtn.dataset.pmBound = '1';
      resumeBtn.addEventListener('click', () => setMode('focus_only'));
    }

    const camSelect = document.getElementById('active-camera-select');
    if (camSelect && !camSelect.dataset.pmBound) {
      camSelect.dataset.pmBound = '1';
      if (camSelect.value) state.focusedCameraId = camSelect.value;
      camSelect.addEventListener('change', (e) => syncCameraFocus(e.target.value));
    }

    if (!state.initialized) {
      window.addEventListener('tab-changed', (e) => {
        const nextTab = e?.detail?.activeTab;
        if (nextTab) syncTabChange(nextTab);
      });
      document.addEventListener('visibilitychange', () => {
        syncVisibility();
      });
      window.addEventListener('focus', () => {
        if (typeof document === 'undefined' || !document.hidden) syncVisibility();
      });
    }
  }

  function init() {
    bindEvents();
    const savedMode = readStoredMode();
    if (savedMode) {
      state.mode = savedMode;
      renderUI();
      state.initialized = true;
      return postModeUpdate({
        mode: savedMode,
        active_tab: getEffectiveActiveTab(),
      });
    }
    state.initialized = true;
    renderUI();
    return fetchStatus();
  }

  window.ProcessingModeUI = {
    STORAGE_KEY,
    VALID_MODES,
    init,
    setMode,
    syncTabChange,
    syncCameraFocus,
    syncVisibility,
    refresh: fetchStatus,
    getState: () => ({ ...state }),
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init());
  } else {
    init();
  }
})();
