/**
 * Intelligent Tracker - Scenario Studio Media & Freeze Submodule.
 * Handles Studio live MJPEG / recorded video attachment, MediaEmptyState, and freeze toggle.
 */

(function () {
  'use strict';

  let freezeCtrl = null;
  let freezeFallbackState = { frozen: false };

  function resolveStudioMediaElement() {
    const vid = document.getElementById('studio-video-player');
    if (vid && vid.style?.display !== 'none' && (vid.currentSrc || vid.src || vid.getAttribute?.('src'))) {
      return vid;
    }
    return document.getElementById('studio-live-img') || null;
  }

  function clearStudioLiveImage() {
    const img = document.getElementById('studio-live-img');
    if (!img) return;
    if (img.dataset) delete img.dataset.activeStreamSrc;
    if (window.MediaEmptyState) {
      window.MediaEmptyState.showEmpty(img, 'No Active Camera Feed', 'Select a camera or recorded video.');
    } else {
      img.removeAttribute?.('src');
      if (img.style) img.style.display = 'none';
    }
  }

  function syncFreezeButtonVisibility(isVideo, hasTarget) {
    const btn = document.getElementById('btn-studio-freeze-toggle');
    if (!btn) return;
    btn.disabled = Boolean(isVideo || !hasTarget);
    if (isVideo || !hasTarget) {
      freezeFallbackState.frozen = false;
      btn.textContent = '⏸ Freeze Frame';
      btn.setAttribute?.('aria-pressed', 'false');
      btn.classList?.remove?.('active');
      freezeCtrl?.reset?.();
    }
  }

  function applyFrozenUi(btn, img, imageSrc, frozen) {
    freezeFallbackState.frozen = frozen;
    btn.textContent = frozen ? '▶ Resume Live' : '⏸ Freeze Frame';
    btn.setAttribute?.('aria-pressed', frozen ? 'true' : 'false');
    if (frozen) btn.classList?.add?.('active');
    else btn.classList?.remove?.('active');
    if (frozen && img && imageSrc) {
      if (window.MediaEmptyState?.setSource) window.MediaEmptyState.setSource(img, imageSrc);
      else { if (img.style) img.style.display = 'block'; img.src = imageSrc; }
    }
  }

  function bindFreezeControl(getCameraId) {
    const btn = document.getElementById('btn-studio-freeze-toggle');
    const img = document.getElementById('studio-live-img');
    if (!btn) return null;
    if (window.ActiveSourceContext?.bindFreezeToggle) {
      freezeCtrl = window.ActiveSourceContext.bindFreezeToggle({
        button: btn,
        img,
        getCameraId,
        onError: (msg) => window.showToast?.('Freeze Frame', msg, 'warning'),
      });
      return freezeCtrl;
    }
    if (!btn.dataset?.freezeBound) {
      if (btn.dataset) btn.dataset.freezeBound = '1';
      btn.addEventListener('click', async () => {
        const camId = String(getCameraId?.() || '').trim();
        if (freezeFallbackState.frozen) {
          applyFrozenUi(btn, img, null, false);
          if (img && camId) attachStudioMedia(camId, false, true);
          return;
        }
        if (!camId) return;
        const res = await fetch(`/api/cameras/${encodeURIComponent(camId)}/freeze_frame`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data?.image_base64) return;
        applyFrozenUi(btn, img, data.image_base64, true);
      });
    }
    return { isFrozen: () => freezeFallbackState.frozen };
  }

  function attachStudioMedia(targetId, isVideo, isActive = true) {
    const img = document.getElementById('studio-live-img');
    const vid = document.getElementById('studio-video-player');
    syncFreezeButtonVisibility(isVideo, Boolean(targetId));
    if (isVideo) {
      if (img) {
        if (img.dataset) delete img.dataset.activeStreamSrc;
        if (window.MediaEmptyState) window.MediaEmptyState.hideEmpty(img, 'none');
        img.removeAttribute?.('src');
        if (img.style) img.style.display = 'none';
      }
      if (vid && targetId) {
        if (vid.style) vid.style.display = 'block';
        vid.src = `/videos/${encodeURIComponent(targetId)}`;
        vid.load?.();
      }
      return;
    }
    if (vid) {
      vid.pause?.();
      vid.removeAttribute?.('src');
      if (vid.style) vid.style.display = 'none';
    }
    if (img && targetId) {
      const streamBase = `/stream/${encodeURIComponent(targetId)}`;
      if (img.dataset) img.dataset.activeStreamSrc = streamBase;
      if (isActive) {
        if (window.MediaEmptyState) window.MediaEmptyState.setSource(img, `${streamBase}?t=${Date.now()}`);
        else { if (img.style) img.style.display = 'block'; img.src = `${streamBase}?t=${Date.now()}`; }
      }
    } else if (img && !targetId && window.MediaEmptyState) {
      window.MediaEmptyState.showEmpty(img, 'No Active Camera Feed', 'Select a camera or recorded video.');
    }
  }

  window.StudioMedia = {
    resolveStudioMediaElement,
    clearStudioLiveImage,
    syncFreezeButtonVisibility,
    bindFreezeControl,
    attachStudioMedia,
  };
})();
