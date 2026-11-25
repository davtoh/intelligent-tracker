/**
 * Unified Enrollment Stage Controller.
 * Manages source context badges, single-stage video+canvas overlay sync,
 * true-FPS frame stepping, and video_filename/media_offset_sec metadata.
 */
(function () {
  'use strict';

  function getActiveVideoFilename() {
    const fromScrubber = window.VideoScrubber?.getCurrentFilename?.()
      || window.VideoScrubber?.getActiveFilename?.();
    if (fromScrubber) return String(fromScrubber);
    const player = document.getElementById('scrubber-video-player');
    if (player?.dataset?.filename) return String(player.dataset.filename);
    const src = player?.getAttribute?.('src') || player?.src || '';
    const match = String(src).match(/\/videos\/([^/?#]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function isVideoStudioActive() {
    const tab = document.getElementById('tab-videos');
    if (tab?.classList?.contains('active')) return true;
    return window.App?.getActiveTab?.() === 'tab-videos';
  }

  function resolvePreferredSource(cams, videos, activeCamId, options = {}) {
    const videoList = Array.isArray(videos) ? videos : [];
    const preferVid = Boolean(options.preferVideo || options.videoFilename || isVideoStudioActive());
    const targetFn = options.videoFilename || getActiveVideoFilename();
    if (preferVid && targetFn && videoList.some((v) => (v.filename || v.name) === targetFn)) {
      return `video:${targetFn}`;
    }
    const ctxRef = window.ActiveSourceContext?.get?.();
    if (ctxRef?.kind === 'video' && ctxRef.videoFilename && videoList.some((v) => (v.filename || v.name) === ctxRef.videoFilename)) {
      return `video:${ctxRef.videoFilename}`;
    }
    if (ctxRef?.cameraId) return ctxRef.cameraId;
    return activeCamId || '';
  }

  function syncSourceContext(sourceVal) {
    const val = String(sourceVal || '').trim();
    if (!val || !window.ActiveSourceContext?.set) return;
    if (val.startsWith('video:')) {
      window.ActiveSourceContext.set({ kind: 'video', cameraId: '', videoFilename: val.slice(6) }, { silent: true });
    } else {
      window.ActiveSourceContext.set({ kind: 'camera', cameraId: val, videoFilename: '' }, { silent: true });
    }
  }

  function updateSourceBadge(sourceVal, labelText) {
    const badge = document.getElementById('gallery-enroll-source-badge');
    if (!badge) return;
    if (!sourceVal) {
      badge.textContent = 'Source: Image Upload';
      return;
    }
    if (String(sourceVal).startsWith('video:')) {
      const fn = String(sourceVal).slice(6);
      badge.textContent = `Video: ${fn}`;
      return;
    }
    badge.textContent = `Camera: ${labelText || sourceVal}`;
  }

  function getSelectedSourceMeta(camSelect) {
    const val = camSelect ? (camSelect.value || '') : '';
    const opt = camSelect?.options?.[camSelect.selectedIndex];
    if (val.startsWith('video:')) {
      const vid = document.getElementById('enroll-scrubber-video');
      const fps = Number(opt?.getAttribute?.('data-fps')) || 30;
      const offset = vid && Number.isFinite(Number(vid.currentTime)) ? Number(vid.currentTime) : 0;
      return {
        camera_id: null,
        video_filename: val.slice(6),
        media_offset_sec: Number(offset.toFixed(3)),
        fps,
      };
    }
    return {
      camera_id: val || null,
      video_filename: null,
      media_offset_sec: null,
      fps: 30,
    };
  }

  function syncVideoStageClasses(canvas, isVideo) {
    const vid = document.getElementById('enroll-scrubber-video');
    if (vid) vid.style.display = isVideo ? 'block' : 'none';
    if (canvas?.classList) {
      if (isVideo) canvas.classList.add('is-video-overlay');
      else canvas.classList.remove('is-video-overlay');
    }
  }

  function getActiveVideoCurrentTime() {
    const player = document.getElementById('scrubber-video-player');
    const t = Number(player?.currentTime);
    return Number.isFinite(t) && t > 0 ? t : 0;
  }

  function setLiveToggleButtonState(btn, isLive, disabled = false) {
    if (!btn) return;
    btn.disabled = Boolean(disabled);
    btn.textContent = isLive ? '⏸ Freeze' : '▶ Live';
    btn.setAttribute?.('aria-pressed', isLive ? 'true' : 'false');
    btn.classList?.toggle?.('active', Boolean(isLive));
    if (btn.dataset) btn.dataset.live = isLive ? 'true' : 'false';
  }

  function bindLiveToggle(canvas, placeholder, onFreezeImage) {
    const btn = document.getElementById('btn-enroll-live-toggle');
    const liveImg = document.getElementById('enroll-live-preview-img');
    const camSel = document.getElementById('enroll-camera-select');
    if (!btn) return null;
    let isLive = false;
    let busy = false;
    const stopLive = () => {
      isLive = false;
      if (liveImg) {
        window.MediaEmptyState?.hideEmpty?.(liveImg, 'none');
        liveImg.removeAttribute?.('src');
        if (liveImg.style) liveImg.style.display = 'none';
      }
      const val = String(camSel?.value || '');
      setLiveToggleButtonState(btn, false, !val || val.startsWith('video:'));
    };
    const startLive = (camId) => {
      if (!camId || camId.startsWith('video:')) return false;
      if (canvas?.style) canvas.style.display = 'none';
      if (placeholder?.style) placeholder.style.display = 'none';
      if (liveImg) {
        const src = `/stream/${encodeURIComponent(camId)}?t=${Date.now()}`;
        if (window.MediaEmptyState?.setSource) window.MediaEmptyState.setSource(liveImg, src);
        else { if (liveImg.style) liveImg.style.display = 'block'; liveImg.src = src; }
      }
      isLive = true;
      setLiveToggleButtonState(btn, true, false);
      return true;
    };
    const freezeFromLive = async () => {
      if (busy) return false;
      const camId = String(camSel?.value || '').trim();
      if (!camId || camId.startsWith('video:')) return false;
      busy = true;
      try {
        const res = await fetch(`/api/cameras/${encodeURIComponent(camId)}/freeze_frame`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data?.image_base64) throw new Error(data?.detail || `HTTP ${res.status}`);
        stopLive();
        const loader = onFreezeImage || window.UniversalEnrollment?.loadFreezeImage;
        loader?.(data.image_base64, canvas, placeholder);
        return true;
      } catch (err) {
        if (liveImg && window.MediaEmptyState?.showEmpty) {
          window.MediaEmptyState.showEmpty(liveImg, 'Freeze Frame Unavailable', err?.message || 'Camera offline');
        }
        return false;
      } finally {
        busy = false;
      }
    };
    const toggle = () => (isLive ? freezeFromLive() : startLive(String(camSel?.value || '').trim()));
    if (!btn.dataset?.liveBound) {
      if (btn.dataset) btn.dataset.liveBound = '1';
      btn.addEventListener('click', toggle);
    }
    return { isLive: () => isLive, startLive, freezeFromLive, stopLive, toggle };
  }

  function initStageControls(canvas, placeholder) {
    const ctrl = bindLiveToggle(canvas, placeholder);
    const camSel = document.getElementById('enroll-camera-select');
    if (camSel && !camSel.dataset?.ctxBound) {
      if (camSel.dataset) camSel.dataset.ctxBound = '1';
      camSel.addEventListener('change', (e) => {
        syncSourceContext(e.target?.value || camSel.value || '');
        ctrl?.stopLive?.();
      });
    }
    return ctrl;
  }

  window.EnrollmentStageController = {
    getActiveVideoFilename,
    getActiveVideoCurrentTime,
    isVideoStudioActive,
    resolvePreferredSource,
    syncSourceContext,
    updateSourceBadge,
    getSelectedSourceMeta,
    syncVideoStageClasses,
    bindLiveToggle,
    initStageControls,
  };
})();
