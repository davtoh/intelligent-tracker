/**
 * Intelligent Tracker - Multi-View WebSocket Transport Client.
 * Manages a single lazy /ws/multiview socket with replace-set subscriptions,
 * idle/pagehide close, visibility pause/resume, exponential backoff, and
 * automatic 3-failure MJPEG fallback with background WS auto-restore.
 */

(function () {
  'use strict';

  const WS_OPEN = 1;
  const WS_CLOSING = 2;
  const IDLE_CLOSE_MS = 30000;
  const BACKOFF_BASE_MS = 1000;
  const BACKOFF_MAX_MS = 60000;
  const FALLBACK_THRESHOLD = 3;

  function buildWsUrl(client) {
    const token = client._token || client._win?.MULTIVIEW_TOKEN || '';
    let base = client._urlOverride;
    if (!base) {
      const loc = client._win?.location || { protocol: 'http:', host: '' };
      const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
      base = `${proto}//${loc.host}/ws/multiview`;
    }
    if (!token) return base;
    const sep = base.includes('?') ? '&' : '?';
    return `${base}${sep}token=${encodeURIComponent(token)}`;
  }

  function computeBackoffMs(client) {
    const exp = Math.pow(2, client._retryAttempt);
    return Math.min(client._backoffMaxMs, Math.round(client._backoffBaseMs * exp));
  }

  function clearIdleTimer(client) {
    if (client._idleTimer) {
      client._clearTimer(client._idleTimer);
      client._idleTimer = null;
    }
  }

  function clearRetryTimer(client) {
    if (client._retryTimer) {
      client._clearTimer(client._retryTimer);
      client._retryTimer = null;
    }
  }

  function scheduleIdleClose(client) {
    clearIdleTimer(client);
    client._idleTimer = client._setTimer(() => {
      client._idleTimer = null;
      if (!client._desired) client.close('idle');
    }, client._idleCloseMs);
  }

  function scheduleReconnect(client) {
    if (client._retryTimer || client._paused) return;
    if (!client._desired || client._desired.cameras.length === 0) return;
    const delay = computeBackoffMs(client);
    client._retryAttempt += 1;
    client._retryTimer = client._setTimer(() => {
      client._retryTimer = null;
      if (!client._paused && client._desired && client._desired.cameras.length > 0) {
        client._connect();
      }
    }, delay);
  }

  function sendJsonPayload(client, payload) {
    if (!client._ws || client._ws.readyState !== WS_OPEN) return false;
    try {
      client._ws.send(JSON.stringify(payload));
      return true;
    } catch (_) {
      return false;
    }
  }

  function sendCurrentSubscription(client) {
    const proto = client._win?.MultiviewProtocol || window.MultiviewProtocol;
    if (!client._desired || !proto) return false;
    const { cameras, layout, options } = client._desired;
    const sent = sendJsonPayload(client, proto.buildSubscribeMessage(cameras, layout, options));
    if (sent) {
      client._subscribedOnSocket = true;
      client._dirtyWhilePaused = false;
    }
    return sent;
  }

  function dispatchBinaryData(client, bufferOrView) {
    const proto = client._win?.MultiviewProtocol || window.MultiviewProtocol;
    if (!proto) return;
    try {
      const frame = proto.parseBinaryFrame(bufferOrView);
      client.onFrame?.(frame);
    } catch (_) {
      // Drop malformed binary frames without disrupting session
    }
  }

  function dispatchControlData(client, rawText) {
    const proto = client._win?.MultiviewProtocol || window.MultiviewProtocol;
    const msg = proto?.parseControlMessage(rawText);
    if (!msg) return;
    if (msg.type === 'hello') {
      client._serverHello = msg;
    } else if (msg.type === 'source_status') {
      client.onSourceStatus?.(msg.camera_id, msg.status, msg.reason || '');
    } else if (msg.type === 'subscribed' && msg.rejected) {
      Object.entries(msg.rejected).forEach(([cid, reason]) => {
        const mapped = reason === 'disabled' ? 'disabled' : 'offline';
        client.onSourceStatus?.(cid, mapped, reason);
      });
    }
    client.onControl?.(msg);
  }

  function dispatchWsMessage(client, eventData) {
    if (typeof eventData === 'string') {
      dispatchControlData(client, eventData);
    } else if (eventData && typeof eventData.arrayBuffer === 'function') {
      eventData.arrayBuffer().then((buf) => dispatchBinaryData(client, buf)).catch(() => {});
    } else if (eventData) {
      dispatchBinaryData(client, eventData);
    }
  }

  function handleWsOpen(client, ws) {
    if (client._ws !== ws) return;
    client._consecutiveFailures = 0;
    client._retryAttempt = 0;
    client._subscribedOnSocket = false;
    const wasDegraded = client._degraded;
    client._degraded = false;
    if (wasDegraded) {
      client.onTransportChange?.('ws', { restored: true });
    }
    if (!client._subscribedOnSocket) {
      if (client._desired && client._desired.cameras.length > 0 && !client._paused) {
        sendCurrentSubscription(client);
      } else if (!client._desired) {
        scheduleIdleClose(client);
      }
    }
  }

  function handleWsClose(client, ev, ws) {
    if (client._ws !== ws || ws._closedHandled) return;
    ws._closedHandled = true;
    client._ws = null;
    client._subscribedOnSocket = false;
    clearIdleTimer(client);
    if (client._intentionalClose) {
      client._intentionalClose = false;
      return;
    }
    const code = typeof ev?.code === 'number' ? ev.code : 1006;
    let enteredFallback = false;
    if (code !== 1000 && code !== 1001) {
      client._consecutiveFailures += 1;
      if (client._consecutiveFailures >= client._fallbackThreshold && !client._degraded) {
        client._degraded = true;
        enteredFallback = true;
      }
    }
    scheduleReconnect(client);
    if (enteredFallback) {
      client.onTransportChange?.('mjpeg-fallback', {
        failures: client._consecutiveFailures,
        code,
      });
    }
  }

  function bindLifecycleEvents(client) {
    const doc = client._doc;
    const win = client._win;
    if (doc && typeof doc.addEventListener === 'function') {
      doc.addEventListener('visibilitychange', () => {
        if (doc.hidden) client.pause();
        else client.resume();
      });
    }
    if (win && typeof win.addEventListener === 'function') {
      win.addEventListener('pagehide', () => client.close('pagehide'));
      win.addEventListener('beforeunload', () => client.close('beforeunload'));
    }
  }

  class MultiviewWsClient {
    constructor(options = {}) {
      this._win = options.win || (typeof window !== 'undefined' ? window : {});
      this._doc = options.doc || (typeof document !== 'undefined' ? document : null);
      this._urlOverride = options.url || '';
      this._token = options.token || '';
      this._wsFactory = options.wsFactory || ((u) => new (this._win.WebSocket || WebSocket)(u));
      this._setTimer = options.setTimer || ((fn, ms) => setTimeout(fn, ms));
      this._clearTimer = options.clearTimer || ((id) => clearTimeout(id));
      this._idleCloseMs = options.idleCloseMs ?? IDLE_CLOSE_MS;
      this._backoffBaseMs = options.backoffBaseMs ?? BACKOFF_BASE_MS;
      this._backoffMaxMs = options.backoffMaxMs ?? BACKOFF_MAX_MS;
      this._fallbackThreshold = options.fallbackThreshold ?? FALLBACK_THRESHOLD;

      this.onFrame = options.onFrame || null;
      this.onSourceStatus = options.onSourceStatus || null;
      this.onTransportChange = options.onTransportChange || null;
      this.onControl = options.onControl || null;

      this._ws = null;
      this._desired = null;
      this._serverHello = null;
      this._paused = Boolean(this._doc?.hidden);
      this._degraded = false;
      this._consecutiveFailures = 0;
      this._retryAttempt = 0;
      this._intentionalClose = false;
      this._subscribedOnSocket = false;
      this._dirtyWhilePaused = false;
      this._idleTimer = null;
      this._retryTimer = null;

      if (options.bindLifecycle !== false) bindLifecycleEvents(this);
    }

    _connect() {
      if (this._ws && this._ws.readyState < WS_CLOSING) return;
      clearRetryTimer(this);
      this._intentionalClose = false;
      this._subscribedOnSocket = false;
      let ws;
      try {
        ws = this._wsFactory(buildWsUrl(this));
      } catch (_) {
        const fakeWs = { _closedHandled: false };
        this._ws = fakeWs;
        handleWsClose(this, { code: 1006 }, fakeWs);
        return;
      }
      ws.binaryType = 'arraybuffer';
      this._ws = ws;
      ws.onopen = () => handleWsOpen(this, ws);
      ws.onmessage = (ev) => dispatchWsMessage(this, ev?.data);
      ws.onerror = () => {
        if (ws.readyState === WS_OPEN && typeof ws.close === 'function') {
          try { ws.close(); } catch (err) { console.debug('[MultiviewClient] Error closing failed WS:', err); }
        }
      };
      ws.onclose = (ev) => handleWsClose(this, ev, ws);
    }

    subscribe(cameras, layout = '2x2', options = {}) {
      clearIdleTimer(this);
      if (!Array.isArray(cameras) || cameras.length === 0) {
        this.unsubscribeAll();
        return;
      }
      this._desired = { cameras: cameras.slice(), layout, options: options || {} };
      if (this._paused) {
        this._dirtyWhilePaused = true;
        return;
      }
      if (this._ws && this._ws.readyState === WS_OPEN) {
        sendCurrentSubscription(this);
      } else if ((!this._ws || this._ws.readyState >= WS_CLOSING) && !this._retryTimer) {
        this._connect();
      }
    }

    unsubscribeAll() {
      this._desired = null;
      this._dirtyWhilePaused = false;
      clearRetryTimer(this);
      if (this._ws && this._ws.readyState === WS_OPEN) {
        const proto = this._win?.MultiviewProtocol || window.MultiviewProtocol;
        if (proto) sendJsonPayload(this, proto.buildControlMessage('unsubscribe_all'));
        this._subscribedOnSocket = false;
        scheduleIdleClose(this);
      }
    }

    pause() {
      if (this._paused) return;
      this._paused = true;
      clearRetryTimer(this);
      if (this._ws && this._ws.readyState === WS_OPEN && this._desired) {
        const proto = this._win?.MultiviewProtocol || window.MultiviewProtocol;
        if (proto) sendJsonPayload(this, proto.buildControlMessage('pause'));
      }
    }

    resume() {
      if (!this._paused) return;
      this._paused = false;
      if (!this._desired || this._desired.cameras.length === 0) return;
      if (this._ws && this._ws.readyState === WS_OPEN) {
        const proto = this._win?.MultiviewProtocol || window.MultiviewProtocol;
        if (proto) sendJsonPayload(this, proto.buildControlMessage('resume'));
        if (this._dirtyWhilePaused) sendCurrentSubscription(this);
      } else if (!this._ws || this._ws.readyState >= WS_CLOSING) {
        this._connect();
      }
    }

    close(reason = 'client_close') {
      clearIdleTimer(this);
      clearRetryTimer(this);
      const ws = this._ws;
      this._ws = null;
      this._subscribedOnSocket = false;
      if (ws) {
        this._intentionalClose = true;
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        if (typeof ws.close === 'function' && (ws.readyState === undefined || ws.readyState < WS_CLOSING)) {
          try { ws.close(1000, reason); } catch (err) { console.debug('[MultiviewClient] Error closing WS:', err); }
        }
      }
      this._intentionalClose = false;
    }

    isDegraded() {
      return Boolean(this._degraded);
    }

    getState() {
      return {
        connected: Boolean(this._ws && this._ws.readyState === WS_OPEN),
        degraded: Boolean(this._degraded),
        paused: Boolean(this._paused),
        consecutiveFailures: this._consecutiveFailures,
        retryAttempt: this._retryAttempt,
        desired: this._desired ? { ...this._desired, cameras: this._desired.cameras.slice() } : null,
      };
    }
  }

  window.MultiviewWsClientClass = MultiviewWsClient;
  window.MultiviewWsClient = new MultiviewWsClient();
})();
