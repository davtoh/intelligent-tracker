/**
 * Intelligent Tracker - Canvas FrameSurface for Multi-View Tiles.
 * Handles monotonic sequence gating, safe ImageBitmap cleanup, DPR ResizeObserver,
 * and source status poster rendering.
 */

(function () {
  'use strict';

  const STATUS_POSTERS = {
    connecting: { label: 'CONNECTING', detail: 'Waiting for stream...', accent: '#06b6d4' },
    hibernating: { label: 'HIBERNATING', detail: 'Stream sleeping', accent: '#64748b' },
    reconnecting: { label: 'RECONNECTING', detail: 'Restoring camera link...', accent: '#f59e0b' },
    error: { label: 'SOURCE ERROR', detail: 'Camera read failed', accent: '#ef4444' },
    offline: { label: 'OFFLINE', detail: 'Camera disconnected', accent: '#ef4444' },
    disabled: { label: 'DISABLED', detail: 'Channel disabled', accent: '#475569' },
  };

  function defaultDecodeBitmap(jpegBytes) {
    if (typeof createImageBitmap !== 'function' || typeof Blob !== 'function') {
      return Promise.reject(new Error('ImageBitmap API unavailable'));
    }
    const blob = new Blob([jpegBytes], { type: 'image/jpeg' });
    return createImageBitmap(blob);
  }

  function isNewerSeq(seq, lastSeq) {
    if (typeof window !== 'undefined' && window.MultiviewProtocol?.isNewerSeq) {
      return window.MultiviewProtocol.isNewerSeq(seq, lastSeq);
    }
    if (lastSeq === null || lastSeq === undefined) return true;
    const diff = (seq - lastSeq) >>> 0;
    return diff > 0 && diff < 0x80000000;
  }

  class FrameSurface {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.ctx = canvas?.getContext?.('2d') || null;
      this.cameraId = options.cameraId || canvas?.getAttribute?.('data-camera-id') || '';
      this.lastDrawnSeq = null;
      this.lastTsMs = 0;
      this.hasFrame = false;
      this.destroyed = false;
      this.status = options.initialStatus || 'connecting';
      this.statusReason = options.initialReason || '';
      this._decodeFn = typeof options.decodeBitmap === 'function' ? options.decodeBitmap : defaultDecodeBitmap;
      this._dpr = 1;
      this._resizeObserver = null;

      this.syncSize();
      const target = canvas?.parentElement || canvas;
      if (typeof ResizeObserver === 'function' && target) {
        this._resizeObserver = new ResizeObserver(() => {
          if (!this.destroyed) this.syncSize();
        });
        this._resizeObserver.observe(target);
      }
    }

    syncSize() {
      if (!this.canvas || this.destroyed) return;
      const rect = this.canvas.getBoundingClientRect?.();
      const cssW = rect && rect.width > 0 ? rect.width : (this.canvas.clientWidth || 320);
      const cssH = rect && rect.height > 0 ? rect.height : (this.canvas.clientHeight || 180);
      const rawDpr = typeof window !== 'undefined' ? Number(window.devicePixelRatio) || 1 : 1;
      this._dpr = Math.max(1, Math.min(rawDpr, 3));

      const targetW = Math.max(1, Math.round(cssW * this._dpr));
      const targetH = Math.max(1, Math.round(cssH * this._dpr));
      if (this.canvas.width !== targetW || this.canvas.height !== targetH) {
        this.canvas.width = targetW;
        this.canvas.height = targetH;
      }
      if (!this.hasFrame) {
        this.renderStatusPoster(this.status, this.statusReason);
      }
    }

    async pushFrame(jpegBytes, seq, captureTsMs = 0) {
      if (this.destroyed || !this.canvas || !this.ctx) return false;
      const isRestartReset = this.lastDrawnSeq !== null && seq < this.lastDrawnSeq && captureTsMs > this.lastTsMs;
      if (!isRestartReset && !isNewerSeq(seq, this.lastDrawnSeq)) return false;

      let bitmap = null;
      try {
        bitmap = await this._decodeFn(jpegBytes);
        if (this.destroyed || !bitmap || (!isRestartReset && !isNewerSeq(seq, this.lastDrawnSeq))) {
          return false;
        }
        this._drawBitmapCover(bitmap);
        this.lastDrawnSeq = seq;
        this.lastTsMs = captureTsMs;
        this.hasFrame = true;
        this.status = 'online';
        this.statusReason = '';
        if (this.canvas?.dataset) {
          this.canvas.dataset.frameSeq = String(seq ?? '');
          this.canvas.dataset.captureTsMs = String(captureTsMs ?? 0);
        }
        return true;
      } catch (_) {
        return false;
      } finally {
        if (bitmap && typeof bitmap.close === 'function') {
          bitmap.close();
        }
      }
    }

    _drawBitmapCover(bitmap) {
      if (!this.ctx || !this.canvas) return;
      const cw = this.canvas.width || 320;
      const ch = this.canvas.height || 180;
      const bw = bitmap.width || 0;
      const bh = bitmap.height || 0;
      if (bw <= 0 || bh <= 0) {
        this.ctx.drawImage(bitmap, 0, 0, cw, ch);
        return;
      }
      const scale = Math.max(cw / bw, ch / bh);
      const sw = cw / scale;
      const sh = ch / scale;
      const sx = Math.max(0, (bw - sw) / 2);
      const sy = Math.max(0, (bh - sh) / 2);
      this.ctx.drawImage(bitmap, sx, sy, sw, sh, 0, 0, cw, ch);
    }

    setStatus(status, reason = '') {
      if (this.destroyed) return;
      this.status = status || 'offline';
      this.statusReason = reason || '';
      if (this.status !== 'online') {
        this.hasFrame = false;
        this.renderStatusPoster(this.status, this.statusReason);
      } else if (!this.hasFrame) {
        this.renderStatusPoster('connecting', '');
      }
    }

    renderStatusPoster(status, reason = '') {
      if (!this.ctx || !this.canvas || this.destroyed) return;
      const cw = this.canvas.width || 320;
      const ch = this.canvas.height || 180;
      const key = status === 'online' ? 'connecting' : status;
      const meta = STATUS_POSTERS[key] || STATUS_POSTERS.offline;
      const dpr = this._dpr || 1;

      this.ctx.fillStyle = '#0f172a';
      this.ctx.fillRect(0, 0, cw, ch);
      this.ctx.fillStyle = meta.accent;
      this.ctx.fillRect(cw * 0.35, (ch / 2) - (20 * dpr), cw * 0.3, 3 * dpr);

      this.ctx.textAlign = 'center';
      this.ctx.textBaseline = 'middle';
      this.ctx.fillStyle = '#e2e8f0';
      this.ctx.font = `600 ${Math.round(13 * dpr)}px Inter, sans-serif`;
      this.ctx.fillText(meta.label, cw / 2, (ch / 2) + (2 * dpr));

      this.ctx.fillStyle = '#94a3b8';
      this.ctx.font = `400 ${Math.round(11 * dpr)}px Inter, sans-serif`;
      this.ctx.fillText(reason || meta.detail, cw / 2, (ch / 2) + (22 * dpr));
    }

    resetSeq() {
      this.lastDrawnSeq = null;
      if (this.canvas?.dataset) {
        delete this.canvas.dataset.frameSeq;
        delete this.canvas.dataset.captureTsMs;
      }
    }

    getFrameSeq() {
      return this.lastDrawnSeq;
    }

    destroy() {
      this.destroyed = true;
      if (this._resizeObserver && typeof this._resizeObserver.disconnect === 'function') {
        this._resizeObserver.disconnect();
      }
      this._resizeObserver = null;
      this.ctx = null;
      this.canvas = null;
    }
  }

  window.FrameSurface = FrameSurface;
})();
