/**
 * Shared MediaEmptyState Controller.
 * Prevents broken <img> icons and root-HTML fetches from img.src = '' across
 * #studio-live-img, #static-heatmap-img, #tag-roi-crop-img, #snapshot-modal-img,
 * #enroll-crop-preview-img, and #test-preview-img.
 */
(function () {
  'use strict';

  const TARGET_CONFIGS = [
    { id: 'studio-live-img', emptyTitle: 'No Active Camera Feed', emptySubtitle: 'Select an online camera or recorded video above.', errorTitle: 'Camera Feed Offline', errorSubtitle: 'Stream unavailable or camera offline.' },
    { id: 'static-heatmap-img', emptyTitle: 'No Heatmap Data Yet', emptySubtitle: 'Open Analytics or run detections to generate density.', errorTitle: 'Heatmap Unavailable', errorSubtitle: 'Could not load density heatmap.' },
    { id: 'tag-roi-crop-img', compact: true, emptyTitle: 'No ROI Crop', emptySubtitle: 'Draw a region to preview crop.', errorTitle: 'Crop Unavailable', errorSubtitle: 'Could not load ROI crop.' },
    { id: 'snapshot-modal-img', emptyTitle: 'No Snapshot Available', emptySubtitle: 'Snapshot image could not be loaded.', errorTitle: 'Snapshot Unavailable', errorSubtitle: 'Snapshot failed to load.' },
    { id: 'enroll-crop-preview-img', compact: true, emptyTitle: 'No Crop Selected', emptySubtitle: 'Drag a bounding box on the stage.', errorTitle: 'Crop Preview Unavailable', errorSubtitle: 'Could not render crop preview.' },
    { id: 'test-preview-img', compact: true, emptyTitle: 'No Test Snapshot', emptySubtitle: 'Click Test Connection to preview.', errorTitle: 'Test Snapshot Failed', errorSubtitle: 'Connection preview unavailable.' },
  ];

  function getOrCreateEmptyEl(imgEl) {
    if (!imgEl || !imgEl.id || typeof document === 'undefined') return null;
    const emptyId = `${imgEl.id}-empty-state`;
    let emptyEl = document.getElementById(emptyId);
    if (!emptyEl && imgEl.parentElement && typeof document.createElement === 'function') {
      emptyEl = document.createElement('div');
      emptyEl.id = emptyId;
      emptyEl.className = 'media-empty-state media-empty-hidden';
      emptyEl.innerHTML = '<div class="media-empty-state-icon">📷</div><div class="media-empty-state-title"></div><div class="media-empty-state-sub"></div>';
      if (typeof imgEl.insertAdjacentElement === 'function') imgEl.insertAdjacentElement('afterend', emptyEl);
      else imgEl.parentElement.appendChild?.(emptyEl);
    }
    return emptyEl;
  }

  function showEmpty(imgEl, title = 'Media Unavailable', subtitle = '', compact = false) {
    if (!imgEl) return;
    if (imgEl.style) imgEl.style.display = 'none';
    imgEl.removeAttribute?.('src');
    const emptyEl = getOrCreateEmptyEl(imgEl);
    if (!emptyEl) return;
    emptyEl.classList?.remove?.('media-empty-hidden');
    if (emptyEl.classList) {
      if (compact) emptyEl.classList.add('is-compact');
      else emptyEl.classList.remove('is-compact');
    }
    if (emptyEl.style) emptyEl.style.display = 'flex';
    const titleEl = emptyEl.querySelector?.('.media-empty-state-title');
    const subEl = emptyEl.querySelector?.('.media-empty-state-sub');
    if (titleEl) titleEl.textContent = title;
    if (subEl) subEl.textContent = subtitle;
  }

  function hideEmpty(imgEl, displayMode = 'block') {
    if (!imgEl) return;
    if (imgEl.style) imgEl.style.display = displayMode;
    const emptyEl = imgEl.id && typeof document !== 'undefined' ? document.getElementById(`${imgEl.id}-empty-state`) : null;
    if (emptyEl) {
      emptyEl.classList?.add?.('media-empty-hidden');
      if (emptyEl.style) emptyEl.style.display = 'none';
    }
  }

  function setSource(imgEl, src, opts = {}) {
    if (!imgEl) return;
    const clean = src ? String(src).trim() : '';
    if (!clean) {
      showEmpty(imgEl, opts.emptyTitle || opts.title || 'Media Unavailable', opts.emptySubtitle || opts.subtitle || '', Boolean(opts.compact));
      return;
    }
    hideEmpty(imgEl, opts.display || 'block');
    imgEl.src = clean;
  }

  function bind(imgEl, opts = {}) {
    if (!imgEl || imgEl.dataset?.mediaEmptyBound === '1') return;
    if (imgEl.dataset) imgEl.dataset.mediaEmptyBound = '1';
    getOrCreateEmptyEl(imgEl);
    imgEl.addEventListener?.('load', () => hideEmpty(imgEl, opts.display || 'block'));
    imgEl.addEventListener?.('error', () => showEmpty(imgEl, opts.errorTitle || opts.title || 'Media Unavailable', opts.errorSubtitle || opts.subtitle || '', Boolean(opts.compact)));
    const curSrc = imgEl.getAttribute?.('src') ?? imgEl.src ?? '';
    if (!curSrc) showEmpty(imgEl, opts.emptyTitle || opts.title || 'Media Unavailable', opts.emptySubtitle || opts.subtitle || '', Boolean(opts.compact));
  }

  function bindAll() {
    if (typeof document === 'undefined') return;
    TARGET_CONFIGS.forEach((cfg) => bind(document.getElementById(cfg.id), cfg));
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bindAll);
    else bindAll();
  }

  window.MediaEmptyState = { bind, bindAll, showEmpty, hideEmpty, setSource, TARGET_CONFIGS };
})();
