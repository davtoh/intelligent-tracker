/**
 * Intelligent Tracker - Bounded Off-DOM Avatar LRU Cache for Canvas Overlays.
 * Loads entity avatar thumbnails via off-DOM Image objects (never mounting broken
 * <img> nodes into the DOM) and degrades gracefully on error or zero dimensions.
 */
(function () {
  'use strict';

  const DEFAULT_MAX_ENTRIES = 64;
  const cache = new Map();
  let maxEntries = DEFAULT_MAX_ENTRIES;

  function touchEntry(url, entry) {
    cache.delete(url);
    cache.set(url, entry);
    while (cache.size > maxEntries) {
      const oldestKey = cache.keys().next().value;
      if (oldestKey === undefined) break;
      cache.delete(oldestKey);
    }
  }

  function hasValidDimensions(img) {
    if (!img) return false;
    const w = Number(img.naturalWidth ?? img.width ?? 0);
    const h = Number(img.naturalHeight ?? img.height ?? 0);
    return w > 0 && h > 0;
  }

  function getAvatarImage(url, onReady) {
    const key = typeof url === 'string' ? url.trim() : '';
    if (!key) return null;

    const existing = cache.get(key);
    if (existing) {
      touchEntry(key, existing);
      if (existing.status === 'ready' && hasValidDimensions(existing.img)) {
        return existing.img;
      }
      if (existing.status === 'loading' && typeof onReady === 'function') {
        existing.waiters.push(onReady);
      }
      return null;
    }

    if (typeof Image !== 'function') return null;
    const img = new Image();
    const entry = { status: 'loading', img, waiters: typeof onReady === 'function' ? [onReady] : [] };
    touchEntry(key, entry);

    img.onload = () => {
      entry.status = hasValidDimensions(img) ? 'ready' : 'error';
      const callbacks = entry.waiters.splice(0, entry.waiters.length);
      if (entry.status === 'ready') {
        callbacks.forEach((cb) => { try { cb(img); } catch (_) { /* ignore */ } });
      }
    };
    img.onerror = () => {
      entry.status = 'error';
      entry.img = null;
      entry.waiters.length = 0;
    };
    img.src = key;
    if (img.complete && hasValidDimensions(img)) {
      entry.status = 'ready';
      entry.waiters.length = 0;
      return img;
    }
    return null;
  }

  function drawCircularAvatar(ctx, img, cx, cy, radius, strokeColor = '#ffffff') {
    if (!ctx || !hasValidDimensions(img)) return false;
    if (typeof ctx.arc !== 'function' || typeof ctx.clip !== 'function' || typeof ctx.drawImage !== 'function') {
      return false;
    }
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.closePath();
    ctx.clip();
    ctx.drawImage(img, cx - radius, cy - radius, radius * 2, radius * 2);
    ctx.restore();
    if (typeof ctx.stroke === 'function') {
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 1.25;
      ctx.stroke();
      ctx.restore();
    }
    return true;
  }

  function getStatus(url) {
    const key = typeof url === 'string' ? url.trim() : '';
    return cache.get(key)?.status || 'missing';
  }

  function invalidate(url) { cache.delete(typeof url === 'string' ? url.trim() : ''); }
  function clear() { cache.clear(); }
  function setMaxEntries(limit) { maxEntries = Math.max(4, Number(limit) || DEFAULT_MAX_ENTRIES); }
  function size() { return cache.size; }

  window.OverlayAvatarCache = {
    getAvatarImage, drawCircularAvatar, getStatus, invalidate, clear, setMaxEntries, size,
  };
})();
