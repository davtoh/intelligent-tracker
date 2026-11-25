/**
 * Intelligent Tracker - Shared ActiveSourceContext & Media Freeze Controller.
 * Unifies active camera / recorded video selection across #live, #analytics, #studio,
 * and Enrollment via localStorage['it_active_source_ref'], URL hash pin overrides,
 * availability validation with MediaEmptyState, and /freeze_frame Pause/Resume.
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'it_active_source_ref';
  const LEGACY_CAMERA_KEY = 'it_focused_camera_id';
  const listeners = new Set();

  function parseNumber(val) {
    if (val === undefined || val === null || val === '') return null;
    const n = Number(val);
    return Number.isFinite(n) ? n : null;
  }

  function normalizeBbox(raw) {
    if (Array.isArray(raw) && raw.length >= 4) {
      const nums = raw.slice(0, 4).map(Number);
      return nums.every(Number.isFinite) ? nums : null;
    }
    if (typeof raw === 'string' && raw.trim()) {
      try { return normalizeBbox(raw.trim().startsWith('[') ? JSON.parse(raw) : raw.split(',')); } catch (_) { return null; }
    }
    return null;
  }

  function normalize(raw) {
    if (!raw) return null;
    if (typeof raw === 'string') {
      const trimmed = raw.trim();
      if (!trimmed) return null;
      return trimmed.startsWith('video:')
        ? { kind: 'video', cameraId: '', videoFilename: trimmed.slice(6) }
        : { kind: 'camera', cameraId: trimmed, videoFilename: '' };
    }
    if (typeof raw !== 'object') return null;
    let cameraId = String(raw.cameraId ?? raw.camera_id ?? raw.camera ?? '').trim();
    let videoFilename = String(raw.videoFilename ?? raw.video_filename ?? raw.video ?? '').trim();
    const rawSource = String(raw.source ?? '').trim();
    if (!videoFilename && rawSource.startsWith('video:')) videoFilename = rawSource.slice(6).trim();
    const kind = String(raw.kind || (videoFilename ? 'video' : (cameraId ? 'camera' : ''))).trim();
    if (!cameraId && !videoFilename && !rawSource) return null;
    const out = { kind: kind || 'camera', cameraId, videoFilename };
    if (rawSource && !cameraId && !videoFilename) out.source = rawSource;
    const runId = String(raw.runId ?? raw.run_id ?? '').trim();
    if (runId) out.runId = runId;
    const mediaOffsetSec = parseNumber(raw.mediaOffsetSec ?? raw.media_offset_sec ?? raw.offset_sec);
    if (mediaOffsetSec !== null) out.mediaOffsetSec = mediaOffsetSec;
    const ts = parseNumber(raw.ts);
    if (ts !== null) out.ts = ts;
    const trackId = parseNumber(raw.trackId ?? raw.track_id);
    if (trackId !== null) out.trackId = trackId;
    const entityId = raw.entityId ?? raw.entity_id ?? raw.entity;
    if (entityId !== undefined && entityId !== null && entityId !== '') out.entityId = entityId;
    const zoneId = String(raw.zoneId ?? raw.zone_id ?? raw.zone ?? '').trim();
    if (zoneId) out.zoneId = zoneId;
    const bbox = normalizeBbox(raw.bbox);
    if (bbox) out.bbox = bbox;
    return out;
  }

  function getHashPin() {
    try {
      const rawHash = window.location?.hash || '';
      const qIdx = rawHash.indexOf('?');
      if (qIdx < 0) return null;
      const qs = new URLSearchParams(rawHash.slice(qIdx + 1));
      const p = {};
      qs.forEach((v, k) => { p[k] = v; });
      if (!p.camera && !p.camera_id && !p.video && !p.video_filename && !p.source) return null;
      const ref = window.AppNavigation?.paramsToSourceRef
        ? normalize(window.AppNavigation.paramsToSourceRef(p))
        : normalize(p);
      return ref ? { ...ref, pinned: true } : null;
    } catch (_) {
      return null;
    }
  }

  function get(opts = {}) {
    if (!opts.ignoreHash) {
      const pinned = getHashPin();
      if (pinned) return pinned;
    }
    try {
      const raw = window.localStorage?.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = normalize(JSON.parse(raw));
        if (parsed) return parsed;
      }
      const legacyCam = window.localStorage?.getItem(LEGACY_CAMERA_KEY);
      if (legacyCam) return { kind: 'camera', cameraId: String(legacyCam).trim(), videoFilename: '' };
    } catch (err) { console.debug('[ActiveSourceContext] read skipped:', err); }
    return null;
  }

  function set(rawRef, opts = {}) {
    if (rawRef === null || rawRef === '') {
      try {
        window.localStorage?.removeItem(STORAGE_KEY);
        if (opts.clearLegacy) window.localStorage?.removeItem(LEGACY_CAMERA_KEY);
      } catch (err) { console.debug('[ActiveSourceContext] clear skipped:', err); }
      if (!opts.silent) notify(null);
      return null;
    }
    const ref = normalize(rawRef);
    if (!ref) return null;
    try {
      window.localStorage?.setItem(STORAGE_KEY, JSON.stringify(ref));
      if (ref.kind !== 'video' && ref.cameraId) {
        window.localStorage?.setItem(LEGACY_CAMERA_KEY, ref.cameraId);
      }
    } catch (err) { console.debug('[ActiveSourceContext] write skipped:', err); }
    if (!opts.silent) notify(ref);
    return ref;
  }

  function notify(ref) {
    listeners.forEach((fn) => {
      try { fn(ref); } catch (err) { console.warn('[ActiveSourceContext] listener error:', err); }
    });
    if (typeof window.dispatchEvent === 'function' && typeof CustomEvent === 'function') {
      window.dispatchEvent(new CustomEvent('active-source-changed', { detail: ref }));
    }
  }

  function subscribe(fn) {
    if (typeof fn !== 'function') return () => {};
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function toSelectValue(ref) {
    const norm = normalize(ref);
    if (!norm) return '';
    if (norm.kind === 'video' || norm.videoFilename) return `video:${norm.videoFilename}`;
    return norm.cameraId || norm.source || '';
  }

  function fromSelectValue(val, selectEl = null) {
    const raw = String(val || '').trim();
    if (!raw) return null;
    if (raw.startsWith('video:')) {
      return { kind: 'video', cameraId: '', videoFilename: raw.slice(6) };
    }
    const groupLabel = selectEl?.selectedOptions?.[0]?.parentElement?.label || '';
    if (groupLabel === 'Recorded Videos') {
      return { kind: 'video', cameraId: '', videoFilename: raw };
    }
    return { kind: 'camera', cameraId: raw, videoFilename: '' };
  }

  async function fetchCatalog() {
    const [camRes, vidRes] = await Promise.allSettled([fetch('/api/cameras'), fetch('/api/videos')]);
    let cameras = [];
    let videos = [];
    let camerasOk = false;
    let videosOk = false;
    if (camRes.status === 'fulfilled' && camRes.value?.ok) {
      const data = await camRes.value.json().catch(() => null);
      if (Array.isArray(data)) { cameras = data; camerasOk = true; }
    }
    if (vidRes.status === 'fulfilled' && vidRes.value?.ok) {
      const data = await vidRes.value.json().catch(() => null);
      if (Array.isArray(data)) { videos = data; videosOk = true; }
    }
    return { cameras, videos, camerasOk, videosOk };
  }

  function appendOptGroup(selectEl, label, items, buildOpt) {
    if (!Array.isArray(items) || !items.length || typeof document === 'undefined') return;
    const grp = document.createElement('optgroup');
    grp.label = label;
    items.forEach((item) => {
      const opt = buildOpt(item);
      if (opt) grp.appendChild(opt);
    });
    if ((grp.children && grp.children.length) || (grp.options && grp.options.length)) {
      selectEl.appendChild(grp);
    }
  }

  async function populateSelect(selectEl, opts = {}) {
    if (!selectEl) return { cameras: [], videos: [], camerasOk: false, videosOk: false };
    const catalog = opts.catalog || await fetchCatalog();
    const videoPrefix = opts.videoPrefix !== undefined ? opts.videoPrefix : 'video:';
    selectEl.innerHTML = '';
    if (opts.includeAll) {
      const allOpt = document.createElement('option');
      allOpt.value = '';
      allOpt.textContent = opts.allLabel || 'All Sources';
      selectEl.appendChild(allOpt);
    }
    appendOptGroup(selectEl, 'Camera Profiles', catalog.cameras, (c) => {
      if (!c?.id) return null;
      return Object.assign(document.createElement('option'), {
        value: c.id,
        textContent: c.name ? `${c.name} (${c.id})` : c.id,
      });
    });
    if (opts.includeVideos !== false) {
      appendOptGroup(selectEl, 'Recorded Videos', catalog.videos, (v) => {
        if (!v?.filename) return null;
        return Object.assign(document.createElement('option'), {
          value: `${videoPrefix}${v.filename}`,
          textContent: `🎬 ${v.filename}`,
        });
      });
    }
    const desired = opts.selectedValue !== undefined ? opts.selectedValue : toSelectValue(get());
    if (desired && selectEl.options) {
      const alt = desired.startsWith('video:') ? desired.slice(6) : desired;
      const match = [...selectEl.options].find((o) => o.value === desired || o.value === alt);
      if (match) selectEl.value = match.value;
    }
    return catalog;
  }

  function checkAvailability(rawRef, catalog) {
    const ref = normalize(rawRef);
    if (!ref) return { available: false, kind: '', id: '', title: 'No Source Selected', subtitle: 'Select a camera or recorded video.' };
    if (ref.kind === 'video' || ref.videoFilename) {
      const fn = ref.videoFilename || ref.source || '';
      if (!catalog?.videosOk) return { available: true, kind: 'video', id: fn };
      const match = catalog.videos.find((v) => v?.filename === fn);
      if (match) return { available: true, kind: 'video', id: fn, item: match };
      return { available: false, kind: 'video', id: fn, title: 'Recorded Video Unavailable', subtitle: `Video '${fn}' does not exist.` };
    }
    const camId = ref.cameraId || ref.source || '';
    if (!catalog?.camerasOk) return { available: true, kind: 'camera', id: camId };
    const cam = catalog.cameras.find((c) => c?.id === camId);
    if (cam) return { available: true, kind: 'camera', id: camId, item: cam };
    const vidFallback = !ref.cameraId && catalog.videosOk ? catalog.videos.find((v) => v?.filename === camId) : null;
    if (vidFallback) return { available: true, kind: 'video', id: camId, item: vidFallback };
    return { available: false, kind: 'camera', id: camId, title: 'Camera Unavailable', subtitle: `Camera '${camId}' does not exist.` };
  }

  function showUnavailable(imgEl, info, opts = {}) {
    if (!imgEl || !window.MediaEmptyState?.showEmpty) return;
    const title = info?.title || 'Source Unavailable';
    const subtitle = info?.subtitle || 'Selected camera or recorded video does not exist.';
    window.MediaEmptyState.showEmpty(imgEl, title, subtitle, Boolean(opts.compact));
  }

  function updateFreezeBtnUi(btn, frozen, pauseLabel, resumeLabel) {
    if (!btn) return;
    btn.textContent = frozen ? resumeLabel : pauseLabel;
    btn.setAttribute?.('aria-pressed', frozen ? 'true' : 'false');
    btn.classList?.toggle?.('active', frozen);
    if (btn.dataset) btn.dataset.frozen = frozen ? 'true' : 'false';
  }

  function bindFreezeToggle(opts = {}) {
    const btn = opts.button || (opts.buttonId ? document.getElementById(opts.buttonId) : null);
    const getImg = () => opts.img || (opts.imgId ? document.getElementById(opts.imgId) : null);
    const pauseLabel = opts.pauseLabel || '⏸ Freeze Frame';
    const resumeLabel = opts.resumeLabel || '▶ Resume Live';
    let frozen = false;
    let busy = false;

    const reset = () => {
      frozen = false;
      updateFreezeBtnUi(btn, false, pauseLabel, resumeLabel);
    };

    const resume = () => {
      const img = getImg();
      const camId = String(opts.getCameraId?.() || '').trim();
      reset();
      if (typeof opts.onResume === 'function') {
        opts.onResume(camId, img);
        return true;
      }
      if (img && camId) {
        const base = (img.dataset?.activeStreamSrc || `/stream/${encodeURIComponent(camId)}`).split('?')[0];
        const nextSrc = `${base}?t=${Date.now()}`;
        if (window.MediaEmptyState?.setSource) window.MediaEmptyState.setSource(img, nextSrc);
        else { if (img.style) img.style.display = 'block'; img.src = nextSrc; }
      }
      return true;
    };

    const freeze = async () => {
      if (busy) return false;
      const img = getImg();
      const camId = String(opts.getCameraId?.() || '').trim();
      if (!camId) {
        opts.onError?.('Select an active camera first.');
        return false;
      }
      busy = true;
      try {
        const res = await fetch(`/api/cameras/${encodeURIComponent(camId)}/freeze_frame`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data?.image_base64) {
          throw new Error(data?.detail || `HTTP ${res.status}`);
        }
        if (img) {
          if (img.dataset && !img.dataset.activeStreamSrc) {
            img.dataset.activeStreamSrc = `/stream/${encodeURIComponent(camId)}`;
          }
          if (window.MediaEmptyState?.setSource) window.MediaEmptyState.setSource(img, data.image_base64);
          else { if (img.style) img.style.display = 'block'; img.src = data.image_base64; }
        }
        frozen = true;
        updateFreezeBtnUi(btn, true, pauseLabel, resumeLabel);
        opts.onFreeze?.(data, img);
        return true;
      } catch (err) {
        opts.onError?.(err?.message || 'Failed to capture freeze frame');
        return false;
      } finally {
        busy = false;
      }
    };

    const toggle = () => (frozen ? resume() : freeze());
    if (btn && !btn.dataset?.freezeBound) {
      if (btn.dataset) btn.dataset.freezeBound = '1';
      btn.addEventListener('click', toggle);
    }
    return { isFrozen: () => frozen, freeze, resume, toggle, reset };
  }

  window.ActiveSourceContext = {
    STORAGE_KEY,
    LEGACY_CAMERA_KEY,
    normalize,
    getHashPin,
    get,
    set,
    subscribe,
    toSelectValue,
    fromSelectValue,
    fetchCatalog,
    populateSelect,
    checkAvailability,
    showUnavailable,
    bindFreezeToggle,
  };
})();
