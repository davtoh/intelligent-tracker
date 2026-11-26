/**
 * Intelligent Tracker - Scenario Studio Canvas Drawing Submodule.
 * Handles mouse interactions and vector overlay rendering for zones, tripwires, and homography.
 */

(function () {
  'use strict';

  function resolveStudioMediaElement() {
    const vid = document.getElementById('studio-video-player');
    if (vid && vid.style?.display !== 'none' && (vid.currentSrc || vid.src || vid.getAttribute?.('src'))) {
      return vid;
    }
    return document.getElementById('studio-live-img') || null;
  }

  function attachStudioMedia(targetId, isVideo, isActive = true) {
    const img = document.getElementById('studio-live-img');
    const vid = document.getElementById('studio-video-player');
    if (isVideo) {
      if (img) {
        if (img.dataset) delete img.dataset.activeStreamSrc;
        img.removeAttribute?.('src');
        img.src = '';
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
      if (img.style) img.style.display = 'block';
      const streamBase = `/stream/${encodeURIComponent(targetId)}`;
      if (img.dataset) img.dataset.activeStreamSrc = streamBase;
      if (isActive) img.src = `${streamBase}?t=${Date.now()}`;
    }
  }

  function syncCanvasBox(canvas, mediaEl) {
    if (!canvas) return null;
    const media = mediaEl || resolveStudioMediaElement();
    const mw = Number(media?.naturalWidth || media?.videoWidth) || 0;
    const mh = Number(media?.naturalHeight || media?.videoHeight) || 0;
    if (!mw || !mh) return null;
    if (canvas.width !== mw || canvas.height !== mh) {
      canvas.width = mw;
      canvas.height = mh;
    }
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
    return {
      x: Math.round((evt.clientX - rect.left) * scaleX),
      y: Math.round((evt.clientY - rect.top) * scaleY),
    };
  }

  function drawZoneOverlay(ctx, pts, cursorPt) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) {
      ctx.lineTo(pts[i][0], pts[i][1]);
    }
    if (cursorPt) ctx.lineTo(cursorPt.x, cursorPt.y);
    ctx.closePath();
    ctx.fillStyle = 'rgba(0, 200, 100, 0.25)';
    ctx.fill();
    ctx.strokeStyle = '#00ff88';
    ctx.lineWidth = 2;
    ctx.stroke();

    for (let i = 0; i < pts.length; i++) {
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(pts[i][0], pts[i][1], 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#00ff88';
      ctx.stroke();
    }
  }

  function drawTripwireOverlay(ctx, pts, cursorPt) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    const endX = cursorPt ? cursorPt.x : (pts[1] ? pts[1][0] : pts[0][0]);
    const endY = cursorPt ? cursorPt.y : (pts[1] ? pts[1][1] : pts[0][1]);
    ctx.lineTo(endX, endY);
    ctx.strokeStyle = '#facc15';
    ctx.lineWidth = 3;
    ctx.stroke();

    const dx = endX - pts[0][0];
    const dy = endY - pts[0][1];
    const len = Math.hypot(dx, dy);
    if (len > 20) {
      const midX = (pts[0][0] + endX) / 2;
      const midY = (pts[0][1] + endY) / 2;
      const nx = -dy / len;
      const ny = dx / len;
      ctx.beginPath();
      ctx.moveTo(midX, midY);
      ctx.lineTo(midX + nx * 25, midY + ny * 25);
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 2;
      ctx.stroke();

      ctx.fillStyle = '#38bdf8';
      ctx.beginPath();
      ctx.arc(midX + nx * 25, midY + ny * 25, 4, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function drawHomographyOverlay(ctx, pts) {
    if (pts.length > 1) {
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) {
        ctx.lineTo(pts[i][0], pts[i][1]);
      }
      if (pts.length === 4) {
        ctx.closePath();
        ctx.fillStyle = 'rgba(14, 165, 233, 0.2)';
        ctx.fill();
      }
      ctx.strokeStyle = '#0ea5e9';
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    const cornerNames = ['1: TL', '2: TR', '3: BR', '4: BL'];
    for (let i = 0; i < pts.length; i++) {
      ctx.fillStyle = '#0ea5e9';
      ctx.beginPath();
      ctx.arc(pts[i][0], pts[i][1], 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 12px Inter, sans-serif';
      ctx.fillText(cornerNames[i] || `${i + 1}`, pts[i][0] + 8, pts[i][1] - 8);
    }
  }

  function drawSavedScenario(ctx, canvas, saved) {
    const overlay = window.UnifiedCanvasOverlay;
    if (!overlay || !saved) return;
    const transform = { offsetX: 0, offsetY: 0, scaleX: 1, scaleY: 1, renderW: canvas.width, renderH: canvas.height };
    if (Array.isArray(saved.zones) && saved.zones.length > 0) {
      overlay.drawZones?.(ctx, saved.zones, transform);
    }
    if (Array.isArray(saved.tripwires) && saved.tripwires.length > 0) {
      const normalized = saved.tripwires.map((tw) => ({ ...tw, line: tw.line || tw.line_segment }));
      overlay.drawTripwires?.(ctx, normalized, transform);
    }
  }

  function drawStudioOverlay(ctx, canvas, mode, pts, cursorPt, saved = null) {
    if (!ctx || !canvas) return;
    syncCanvasBox(canvas);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawSavedScenario(ctx, canvas, saved);
    if (!pts || pts.length === 0) return;

    ctx.save();
    if (mode === 'draw_zone') {
      drawZoneOverlay(ctx, pts, cursorPt);
    } else if (mode === 'draw_tripwire') {
      drawTripwireOverlay(ctx, pts, cursorPt);
    } else if (mode === 'calibrate_homography') {
      drawHomographyOverlay(ctx, pts);
    }
    ctx.restore();
  }

  function setupCanvasEventListeners(canvas, handlers) {
    if (!canvas) return;
    canvas.addEventListener('click', (evt) => {
      const pt = getCanvasCoords(evt, canvas);
      handlers.onClick?.(pt);
    });
    canvas.addEventListener('mousemove', (evt) => {
      const pt = getCanvasCoords(evt, canvas);
      handlers.onMouseMove?.(pt);
    });
    canvas.addEventListener('dblclick', (evt) => {
      handlers.onDblClick?.();
    });
  }

  window.StudioCanvas = {
    resolveStudioMediaElement: resolveStudioMediaElement,
    attachStudioMedia: attachStudioMedia,
    syncCanvasBox: syncCanvasBox,
    getCanvasCoords: getCanvasCoords,
    drawOverlay: drawStudioOverlay,
    setupListeners: setupCanvasEventListeners,
  };
})();

