/**
 * Intelligent Tracker - Scenario Studio Canvas Drawing Submodule.
 * Handles pointer interactions and vector overlay rendering for zones, tripwires,
 * saved 4-point BEV homography quads, and live/video tracks via UnifiedCanvasOverlay.
 */

(function () {
  'use strict';

  function resolveStudioMediaElement() {
    if (window.StudioMedia?.resolveStudioMediaElement) return window.StudioMedia.resolveStudioMediaElement();
    const vid = document.getElementById('studio-video-player');
    if (vid && vid.style?.display !== 'none' && (vid.currentSrc || vid.src || vid.getAttribute?.('src'))) return vid;
    return document.getElementById('studio-live-img') || null;
  }

  const attachStudioMedia = (id, isVid, active = true) => window.StudioMedia?.attachStudioMedia?.(id, isVid, active);
  const bindFreezeControl = (getCamId) => window.StudioMedia?.bindFreezeControl?.(getCamId) || null;

  function selectZoneById(zoneId, state, callbacks = {}) {
    if (!zoneId || !state) return false;
    const target = (Array.isArray(state.zones) ? state.zones : []).find((z) => z?.id === zoneId || z?.zone_id === zoneId || z?.name === zoneId);
    if (!target) return false;
    state.mode = 'idle';
    window.StudioShapeEditor?.selectShape?.('zone', target.name);
    callbacks.updateStatus?.(`Selected zone '${target.name}'. Drag vertices to edit.`);
    callbacks.drawOverlay?.();
    return true;
  }

  function syncCanvasBox(canvas, mediaEl) {
    if (!canvas) return null;
    const media = mediaEl || resolveStudioMediaElement();
    const mw = Number(media?.naturalWidth || media?.videoWidth) || 0;
    const mh = Number(media?.naturalHeight || media?.videoHeight) || 0;
    if (!mw || !mh) return null;
    if (canvas.width !== mw || canvas.height !== mh) { canvas.width = mw; canvas.height = mh; }
    const overlay = window.UnifiedCanvasOverlay;
    if (!overlay?.computeContainBox || !media.getBoundingClientRect) return null;
    const elemRect = media.getBoundingClientRect();
    const containerRect = media.parentElement?.getBoundingClientRect?.() || { left: 0, top: 0 };
    if (!elemRect.width || !elemRect.height) return null;
    const box = overlay.computeContainBox(elemRect, containerRect, mw, mh);
    if (canvas.style) {
      canvas.style.left = `${box.offsetX}px`;
      canvas.style.top = `${box.offsetY}px`;
      canvas.style.width = `${box.renderW}px`;
      canvas.style.height = `${box.renderH}px`;
    }
    return box;
  }

  function getCanvasCoords(evt, canvas) {
    syncCanvasBox(canvas);
    const rect = canvas.getBoundingClientRect();
    const scaleX = rect.width > 0 ? canvas.width / rect.width : 1;
    const scaleY = rect.height > 0 ? canvas.height / rect.height : 1;
    return { x: Math.round((evt.clientX - rect.left) * scaleX), y: Math.round((evt.clientY - rect.top) * scaleY) };
  }

  function drawZoneOverlay(ctx, pts, cursorPt) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    if (cursorPt) ctx.lineTo(cursorPt.x, cursorPt.y);
    ctx.closePath();
    ctx.fillStyle = 'rgba(0, 200, 100, 0.25)'; ctx.fill();
    ctx.strokeStyle = '#00ff88'; ctx.lineWidth = 2; ctx.stroke();
    for (let i = 0; i < pts.length; i++) {
      ctx.fillStyle = '#ffffff'; ctx.beginPath();
      ctx.arc(pts[i][0], pts[i][1], 5, 0, Math.PI * 2);
      ctx.fill(); ctx.strokeStyle = '#00ff88'; ctx.stroke();
    }
  }

  function drawTripwireOverlay(ctx, pts, cursorPt) {
    const endX = cursorPt ? cursorPt.x : (pts[1] ? pts[1][0] : pts[0][0]);
    const endY = cursorPt ? cursorPt.y : (pts[1] ? pts[1][1] : pts[0][1]);
    ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]); ctx.lineTo(endX, endY);
    ctx.strokeStyle = '#facc15'; ctx.lineWidth = 3; ctx.stroke();
    const dx = endX - pts[0][0], dy = endY - pts[0][1], len = Math.hypot(dx, dy);
    if (len > 20) {
      const midX = (pts[0][0] + endX) / 2, midY = (pts[0][1] + endY) / 2;
      const nx = -dy / len, ny = dx / len;
      ctx.beginPath(); ctx.moveTo(midX, midY); ctx.lineTo(midX + nx * 25, midY + ny * 25);
      ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = '#38bdf8'; ctx.beginPath();
      ctx.arc(midX + nx * 25, midY + ny * 25, 4, 0, Math.PI * 2); ctx.fill();
    }
  }

  function drawHomographyOverlay(ctx, pts, opts = {}) {
    if (!Array.isArray(pts) || pts.length === 0) return;
    ctx.save();
    if (opts.dashed && typeof ctx.setLineDash === 'function') ctx.setLineDash([6, 4]);
    if (pts.length > 1) {
      ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      if (pts.length === 4) { ctx.closePath(); ctx.fillStyle = opts.fillStyle || 'rgba(14, 165, 233, 0.2)'; ctx.fill(); }
      ctx.strokeStyle = opts.strokeStyle || '#0ea5e9'; ctx.lineWidth = 2; ctx.stroke();
    }
    if (typeof ctx.setLineDash === 'function') ctx.setLineDash([]);
    const cornerNames = ['1: TL', '2: TR', '3: BR', '4: BL'];
    for (let i = 0; i < pts.length; i++) {
      ctx.fillStyle = opts.strokeStyle || '#0ea5e9';
      ctx.beginPath(); ctx.arc(pts[i][0], pts[i][1], opts.dashed ? 5 : 6, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#ffffff'; ctx.font = 'bold 12px Inter, sans-serif';
      ctx.fillText(cornerNames[i] || `${i + 1}`, pts[i][0] + 8, pts[i][1] - 8);
    }
    if (opts.label && pts[0]) {
      ctx.fillStyle = '#38bdf8'; ctx.font = 'bold 11px Inter, sans-serif';
      ctx.fillText(opts.label, pts[0][0] + 8, pts[0][1] + 14);
    }
    ctx.restore();
  }

  function drawSavedHomographyQuad(ctx, saved, mode) {
    const quadMode = saved?.bevQuadMode || 'all';
    const pts = saved?.homography?.src_points;
    if (quadMode === 'off' || !Array.isArray(pts) || pts.length < 4) return;
    const isSelected = Boolean(
      saved?.homographySelected || mode === 'calibrate_homography'
      || window.StudioShapeEditor?.getSelected?.()?.type === 'homography'
    );
    if (quadMode === 'selected' && !isSelected) return;
    const { metric_width: mw, metric_height: mh } = saved.homography;
    drawHomographyOverlay(ctx, pts.slice(0, 4), {
      dashed: true, fillStyle: 'rgba(14, 165, 233, 0.14)', strokeStyle: '#38bdf8',
      label: mw && mh ? `BEV ${mw}m × ${mh}m` : 'BEV Quad',
    });
  }

  function drawSavedScenario(ctx, canvas, saved, mode) {
    if (!saved) return;
    const overlay = window.UnifiedCanvasOverlay;
    const vis = saved.overlayVisibility || {};
    const transform = { offsetX: 0, offsetY: 0, scaleX: 1, scaleY: 1, renderW: canvas.width, renderH: canvas.height };
    if (overlay && vis.zones !== false && Array.isArray(saved.zones) && saved.zones.length > 0) {
      overlay.drawZones?.(ctx, saved.zones, transform);
    }
    if (overlay && vis.tripwires !== false && Array.isArray(saved.tripwires) && saved.tripwires.length > 0) {
      overlay.drawTripwires?.(ctx, saved.tripwires.map((tw) => ({ ...tw, line: tw.line || tw.line_segment })), transform);
    }
    drawSavedHomographyQuad(ctx, saved, mode);
    if (overlay?.renderScene && Array.isArray(saved.tracks) && saved.tracks.length > 0) {
      const scales = saved.sourceResolution && overlay.resolveScaleFactors
        ? overlay.resolveScaleFactors(canvas.width, canvas.height, saved.sourceResolution, canvas.width, canvas.height)
        : { scaleX: 1, scaleY: 1 };
      overlay.renderScene(ctx, {
        clear: false,
        transform: { offsetX: 0, offsetY: 0, scaleX: scales.scaleX, scaleY: scales.scaleY, renderW: canvas.width, renderH: canvas.height },
        tracks: saved.tracks,
        visibility: { ...vis, zones: false, tripwires: false, heatmap: false },
      });
    }
  }

  function drawStudioOverlay(ctx, canvas, mode, pts, cursorPt, saved = null) {
    if (!ctx || !canvas) return;
    syncCanvasBox(canvas);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawSavedScenario(ctx, canvas, saved, mode);
    if (mode === 'idle') window.StudioShapeEditor?.drawSelection?.(ctx, canvas, saved);
    if (!pts || pts.length === 0) return;
    ctx.save();
    if (mode === 'draw_zone') drawZoneOverlay(ctx, pts, cursorPt);
    else if (mode === 'draw_tripwire') drawTripwireOverlay(ctx, pts, cursorPt);
    else if (mode === 'calibrate_homography') drawHomographyOverlay(ctx, pts);
    ctx.restore();
  }

  function setupCanvasEventListeners(canvas, handlers) {
    if (!canvas) return;
    let dragging = false, activePointerId = null;
    canvas.addEventListener('click', (evt) => handlers.onClick?.(getCanvasCoords(evt, canvas)));
    const onDown = (evt) => {
      dragging = true;
      if (evt.pointerId !== undefined && typeof canvas.setPointerCapture === 'function') {
        activePointerId = evt.pointerId;
        try { canvas.setPointerCapture(evt.pointerId); } catch (err) { console.debug('StudioCanvas capture:', err); }
      }
      handlers.onMouseDown?.(getCanvasCoords(evt, canvas), evt);
    };
    const onMove = (evt) => handlers.onMouseMove?.(getCanvasCoords(evt, canvas));
    const onUp = (evt) => {
      if (!dragging && evt.currentTarget !== canvas) return;
      dragging = false;
      if (activePointerId !== null && typeof canvas.releasePointerCapture === 'function') {
        try { canvas.releasePointerCapture(activePointerId); } catch (err) { console.debug('StudioCanvas release:', err); }
        activePointerId = null;
      }
      handlers.onMouseUp?.(getCanvasCoords(evt, canvas), evt);
    };
    ['pointerdown', 'mousedown'].forEach((ev) => canvas.addEventListener(ev, onDown));
    ['pointermove', 'mousemove'].forEach((ev) => canvas.addEventListener(ev, onMove));
    ['pointerup', 'mouseup'].forEach((ev) => { canvas.addEventListener(ev, onUp); window.addEventListener(ev, onUp); });
    canvas.addEventListener('dblclick', () => handlers.onDblClick?.());
  }

  window.StudioCanvas = {
    resolveStudioMediaElement, attachStudioMedia, bindFreezeControl,
    selectZoneById, syncCanvasBox, getCanvasCoords,
    drawOverlay: drawStudioOverlay, setupListeners: setupCanvasEventListeners,
  };
})();
