/**
 * Intelligent Tracker - Scenario Studio Canvas Drawing Submodule.
 * Handles mouse interactions and vector overlay rendering for zones, tripwires, and homography.
 */

(function () {
  'use strict';

  function getCanvasCoords(evt, canvas) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
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

  function drawStudioOverlay(ctx, canvas, mode, pts, cursorPt) {
    if (!ctx || !canvas) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
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
    getCanvasCoords: getCanvasCoords,
    drawOverlay: drawStudioOverlay,
    setupListeners: setupCanvasEventListeners,
  };
})();

