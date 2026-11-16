/**
 * Intelligent Tracker - MJPEG Stream Reconnect & Stall Watchdog.
 * Provides bounded exponential-backoff reconnect on <img> error or stall.
 */

(function () {
  'use strict';

  const DEFAULT_BASE_DELAY_MS = 1000;
  const DEFAULT_MAX_DELAY_MS = 30000;
  const DEFAULT_STALL_TIMEOUT_MS = 15000;
  const states = new WeakMap();

  function buildReconnectUrl(rawSrc, nowFn) {
    const base = String(rawSrc || '').trim();
    if (!base || base.startsWith('data:image/svg+xml')) return '';
    const ts = String(typeof nowFn === 'function' ? nowFn() : Date.now());
    const [path, query = ''] = base.split('?');
    const params = query
      ? query.split('&').filter(part => part && !part.startsWith('_r='))
      : [];
    params.push(`_r=${encodeURIComponent(ts)}`);
    return `${path}?${params.join('&')}`;
  }

  function clearTimers(state) {
    if (state.retryTimer) {
      clearTimeout(state.retryTimer);
      state.retryTimer = null;
    }
    if (state.stallTimer) {
      clearTimeout(state.stallTimer);
      state.stallTimer = null;
    }
  }

  function isDetachedOrDisconnected(img, state) {
    return state.detached || (img.isConnected === false);
  }

  function armStallWatchdog(img, state) {
    if (state.stallTimer) {
      clearTimeout(state.stallTimer);
      state.stallTimer = null;
    }
    if (state.stallTimeoutMs <= 0 || isDetachedOrDisconnected(img, state)) return;
    state.stallTimer = setTimeout(() => {
      state.stallTimer = null;
      if (!isDetachedOrDisconnected(img, state)) {
        scheduleReconnect(img, state);
      }
    }, state.stallTimeoutMs);
  }

  function scheduleReconnect(img, state) {
    if (isDetachedOrDisconnected(img, state)) {
      detach(img);
      return;
    }
    if (state.retryTimer) return;
    const delay = Math.min(
      state.baseDelayMs * (2 ** state.attempt),
      state.maxDelayMs
    );
    state.attempt += 1;
    state.retryTimer = setTimeout(() => {
      state.retryTimer = null;
      if (isDetachedOrDisconnected(img, state)) {
        detach(img);
        return;
      }
      const nextUrl = buildReconnectUrl(img.src || state.lastSrc, state.now);
      if (!nextUrl) return;
      state.lastSrc = nextUrl;
      img.src = nextUrl;
      armStallWatchdog(img, state);
    }, delay);
  }

  function attach(img, options = {}) {
    if (!img) return null;
    detach(img);
    const state = {
      attempt: 0,
      detached: false,
      retryTimer: null,
      stallTimer: null,
      lastSrc: img.src || '',
      baseDelayMs: options.baseDelayMs ?? DEFAULT_BASE_DELAY_MS,
      maxDelayMs: options.maxDelayMs ?? DEFAULT_MAX_DELAY_MS,
      stallTimeoutMs: options.stallTimeoutMs ?? DEFAULT_STALL_TIMEOUT_MS,
      now: options.now || Date.now,
      onError: null,
      onLoad: null,
    };
    state.onError = () => scheduleReconnect(img, state);
    state.onLoad = () => {
      state.attempt = 0;
      state.lastSrc = img.src || state.lastSrc;
      armStallWatchdog(img, state);
    };
    img.addEventListener?.('error', state.onError);
    img.addEventListener?.('load', state.onLoad);
    states.set(img, state);
    armStallWatchdog(img, state);
    return state;
  }

  function detach(img) {
    if (!img) return;
    const state = states.get(img);
    if (!state) return;
    state.detached = true;
    clearTimers(state);
    if (state.onError) img.removeEventListener?.('error', state.onError);
    if (state.onLoad) img.removeEventListener?.('load', state.onLoad);
    states.delete(img);
  }

  function detachAll(container) {
    if (!container || typeof container.querySelectorAll !== 'function') return;
    container.querySelectorAll('img').forEach(img => detach(img));
  }

  window.MjpegReconnect = {
    attach: attach,
    detach: detach,
    detachAll: detachAll,
    buildReconnectUrl: buildReconnectUrl,
  };
})();
