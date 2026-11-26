/**
 * Intelligent Tracker - Unified Click-to-Tag & Freehand Drag-to-Draw ROI Controller.
 * Shared pointer interaction engine for #interactive-canvas (#live) and #scrubber-overlay-canvas (#videos).
 */
(function () {
  'use strict';

  const DRAG_THRESHOLD_PX = 6;
  const MIN_SOURCE_ROI_PX = 4;
  const attachments = new WeakMap();
  const dragContexts = new WeakMap();
  let recognitionHandler = null;

  function resolveMediaDimensions(mediaEl, sourceWidth, sourceHeight) {
    const mw = Number(sourceWidth) > 0
      ? Number(sourceWidth)
      : (Number(mediaEl?.naturalWidth) || Number(mediaEl?.videoWidth) || Number(mediaEl?.clientWidth) || 1);
    const mh = Number(sourceHeight) > 0
      ? Number(sourceHeight)
      : (Number(mediaEl?.naturalHeight) || Number(mediaEl?.videoHeight) || Number(mediaEl?.clientHeight) || 1);
    return { mw, mh };
  }

  function mapClientToSourcePoint(clientX, clientY, mediaEl, containerEl, sourceWidth, sourceHeight) {
    const { mw, mh } = resolveMediaDimensions(mediaEl, sourceWidth, sourceHeight);
    const elemRect = typeof mediaEl?.getBoundingClientRect === 'function'
      ? mediaEl.getBoundingClientRect()
      : { left: 0, top: 0, width: mw, height: mh };
    const containerRect = typeof containerEl?.getBoundingClientRect === 'function'
      ? containerEl.getBoundingClientRect()
      : { left: elemRect.left || 0, top: elemRect.top || 0 };
    const overlay = window.UnifiedCanvasOverlay;
    const box = overlay?.computeContainBox
      ? overlay.computeContainBox(elemRect, containerRect, mw, mh)
      : { offsetX: 0, offsetY: 0, renderW: elemRect.width || mw, renderH: elemRect.height || mh, scale: 1 };
    const localX = clientX - (containerRect.left || 0) - box.offsetX;
    const localY = clientY - (containerRect.top || 0) - box.offsetY;
    const rw = box.renderW > 0 ? box.renderW : 1;
    const rh = box.renderH > 0 ? box.renderH : 1;
    const x = Math.max(0, Math.min(mw, (localX / rw) * mw));
    const y = Math.max(0, Math.min(mh, (localY / rh) * mh));
    const inBounds = localX >= 0 && localX <= rw && localY >= 0 && localY <= rh;
    return { x, y, localX, localY, box, inBounds };
  }

  function normalizeDragRect(p1, p2, minSize = MIN_SOURCE_ROI_PX) {
    if (!p1 || !p2) return null;
    const x1 = Number(p1.x);
    const y1 = Number(p1.y);
    const x2 = Number(p2.x);
    const y2 = Number(p2.y);
    if (![x1, y1, x2, y2].every(Number.isFinite)) return null;
    const x = Math.round(Math.min(x1, x2));
    const y = Math.round(Math.min(y1, y2));
    const w = Math.round(Math.abs(x2 - x1));
    const h = Math.round(Math.abs(y2 - y1));
    if (w < minSize || h < minSize) return null;
    return [x, y, w, h];
  }

  function hitTestTrackAtPoint(srcX, srcY, tracks) {
    if (!Array.isArray(tracks) || !Number.isFinite(srcX) || !Number.isFinite(srcY)) return null;
    for (let i = tracks.length - 1; i >= 0; i -= 1) {
      const trk = tracks[i];
      if (!Array.isArray(trk?.bbox) || trk.bbox.length < 4) continue;
      const [bx, by, bw, bh] = trk.bbox;
      if (srcX >= bx && srcX <= bx + bw && srcY >= by && srcY <= by + bh) {
        return trk;
      }
    }
    return null;
  }

  function drawSelectionOverlay(ctx, rect, options = {}) {
    if (!ctx || !rect) return;
    const x = Number(rect.x) || 0;
    const y = Number(rect.y) || 0;
    const w = Number(rect.w) || 0;
    const h = Number(rect.h) || 0;
    if (Math.abs(w) < 1 || Math.abs(h) < 1) return;
    const stroke = options.stroke || '#06b6d4';
    const fill = options.fill || 'rgba(6, 182, 212, 0.16)';
    ctx.save();
    ctx.fillStyle = fill;
    ctx.strokeStyle = stroke;
    ctx.lineWidth = options.lineWidth || 2;
    ctx.setLineDash(options.dash || [6, 4]);
    ctx.fillRect(x, y, w, h);
    ctx.strokeRect(x, y, w, h);
    ctx.setLineDash([]);
    ctx.restore();
  }

  function toCanvasRect(canvas, startClient, curClient) {
    const cRect = typeof canvas.getBoundingClientRect === 'function'
      ? canvas.getBoundingClientRect()
      : { left: 0, top: 0 };
    const x1 = startClient.x - (cRect.left || 0);
    const y1 = startClient.y - (cRect.top || 0);
    const x2 = curClient.x - (cRect.left || 0);
    const y2 = curClient.y - (cRect.top || 0);
    return {
      x: Math.min(x1, x2),
      y: Math.min(y1, y2),
      w: Math.abs(x2 - x1),
      h: Math.abs(y2 - y1),
    };
  }

  function pauseVideoOnDrag(mediaEl) {
    if (mediaEl && typeof mediaEl.pause === 'function' && mediaEl.paused === false) {
      mediaEl.pause();
    }
  }

  function renderDragState(config, state, curClient) {
    const { canvas, onRenderOverlay } = config;
    const ctx = typeof canvas.getContext === 'function' ? canvas.getContext('2d') : null;
    if (typeof onRenderOverlay === 'function') {
      onRenderOverlay();
    } else if (ctx) {
      const cssW = parseFloat(canvas.style?.width) || canvas.clientWidth || canvas.width || 0;
      const cssH = parseFloat(canvas.style?.height) || canvas.clientHeight || canvas.height || 0;
      ctx.clearRect(0, 0, cssW, cssH);
    }
    if (ctx && state.isDragging && curClient) {
      drawSelectionOverlay(ctx, toCanvasRect(canvas, state.startClient, curClient));
    }
  }

  function buildPointerHandlers(config, state) {
    const threshold = Number(config.dragThresholdPx) > 0 ? Number(config.dragThresholdPx) : DRAG_THRESHOLD_PX;
    const getCtxInfo = () => (typeof config.getSourceContext === 'function' ? (config.getSourceContext() || {}) : {});

    const onPointerDown = (e) => {
      if (e.button != null && e.button !== 0) return;
      state.active = true;
      state.isDragging = false;
      state.pointerId = e.pointerId;
      state.startClient = { x: e.clientX, y: e.clientY };
      config.canvas.setPointerCapture?.(e.pointerId);
    };

    const onPointerMove = (e) => {
      if (!state.active) return;
      state.lastClient = { x: e.clientX, y: e.clientY };
      const dist = Math.hypot(e.clientX - state.startClient.x, e.clientY - state.startClient.y);
      if (!state.isDragging && dist >= threshold) {
        state.isDragging = true;
        pauseVideoOnDrag(config.mediaEl);
      }
      if (state.isDragging) {
        renderDragState(config, state, state.lastClient);
      }
    };

    const resetDrag = (e) => {
      if (!state.active) return;
      const wasDragging = state.isDragging;
      state.active = false;
      state.isDragging = false;
      state.lastClient = null;
      if (e?.pointerId != null) config.canvas.releasePointerCapture?.(e.pointerId);
      if (wasDragging) renderDragState(config, state, null);
    };

    const onPointerUp = (e) => {
      if (!state.active) return;
      const wasDragging = state.isDragging;
      const start = state.startClient;
      resetDrag(e);
      const srcCtx = getCtxInfo();
      const container = config.containerEl || config.mediaEl?.parentElement || config.canvas.parentElement;
      const endPt = mapClientToSourcePoint(e.clientX, e.clientY, config.mediaEl, container, srcCtx.sourceWidth, srcCtx.sourceHeight);
      if (wasDragging) {
        const startPt = mapClientToSourcePoint(start.x, start.y, config.mediaEl, container, srcCtx.sourceWidth, srcCtx.sourceHeight);
        const bbox = normalizeDragRect(startPt, endPt);
        if (bbox && typeof config.onRoiDrawn === 'function') {
          config.onRoiDrawn({ bbox, sourceContext: srcCtx });
        }
        return;
      }
      const tracks = typeof config.getTracks === 'function' ? (config.getTracks() || []) : [];
      const track = hitTestTrackAtPoint(endPt.x, endPt.y, tracks);
      if (track && typeof config.onTrackClick === 'function') {
        config.onTrackClick({ track, point: { x: endPt.x, y: endPt.y }, sourceContext: srcCtx });
      }
    };

    return { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: resetDrag };
  }

  function attach(config) {
    if (!config?.canvas) return () => {};
    const prevDetach = attachments.get(config.canvas);
    if (typeof prevDetach === 'function') prevDetach();
    const state = { active: false, isDragging: false, pointerId: null, startClient: { x: 0, y: 0 }, lastClient: null };
    const handlers = buildPointerHandlers(config, state);
    config.canvas.addEventListener('pointerdown', handlers.onPointerDown);
    config.canvas.addEventListener('pointermove', handlers.onPointerMove);
    config.canvas.addEventListener('pointerup', handlers.onPointerUp);
    config.canvas.addEventListener('pointercancel', handlers.onPointerCancel);
    const detach = () => {
      config.canvas.removeEventListener('pointerdown', handlers.onPointerDown);
      config.canvas.removeEventListener('pointermove', handlers.onPointerMove);
      config.canvas.removeEventListener('pointerup', handlers.onPointerUp);
      config.canvas.removeEventListener('pointercancel', handlers.onPointerCancel);
      attachments.delete(config.canvas);
      dragContexts.delete(config.canvas);
    };
    attachments.set(config.canvas, detach);
    dragContexts.set(config.canvas, { config, state });
    return detach;
  }

  function isDragging(canvas) {
    return Boolean(canvas && dragContexts.get(canvas)?.state?.isDragging);
  }

  function redrawDragOverlay(canvas) {
    const entry = canvas ? dragContexts.get(canvas) : null;
    if (!entry?.state?.isDragging || !entry.state.lastClient) return false;
    const ctx = typeof canvas.getContext === 'function' ? canvas.getContext('2d') : null;
    if (!ctx) return false;
    drawSelectionOverlay(ctx, toCanvasRect(canvas, entry.state.startClient, entry.state.lastClient));
    return true;
  }

  function setRecognitionHandler(fn) {
    recognitionHandler = typeof fn === 'function' ? fn : null;
  }

  function openWithRecognition(payload) {
    if (typeof recognitionHandler === 'function') {
      return recognitionHandler(payload);
    }
    return null;
  }

  window.RoiDrawTagger = {
    DRAG_THRESHOLD_PX,
    MIN_SOURCE_ROI_PX,
    mapClientToSourcePoint,
    normalizeDragRect,
    hitTestTrackAtPoint,
    drawSelectionOverlay,
    isDragging,
    redrawDragOverlay,
    attach,
    setRecognitionHandler,
    openWithRecognition,
  };
})();
