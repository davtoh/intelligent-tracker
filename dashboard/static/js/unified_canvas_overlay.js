/**
 * Intelligent Tracker - Unified 100% Client-Side Canvas Overlay Engine.
 * Shared HiDPI (<canvas>) vector rendering for #live and #videos viewports.
 */
(function () {
  'use strict';

  const PALETTES = [
    { id: 'cyan', name: 'Cyan', stroke: '#06b6d4', fill: 'rgba(6, 182, 212, 0.16)', labelBg: 'rgba(8, 145, 178, 0.92)', text: '#ffffff' },
    { id: 'amber', name: 'Amber', stroke: '#f59e0b', fill: 'rgba(245, 158, 11, 0.16)', labelBg: 'rgba(180, 83, 9, 0.92)', text: '#ffffff' },
    { id: 'purple', name: 'Purple', stroke: '#a855f7', fill: 'rgba(168, 85, 247, 0.16)', labelBg: 'rgba(126, 34, 206, 0.92)', text: '#ffffff' },
    { id: 'emerald', name: 'Emerald', stroke: '#10b981', fill: 'rgba(16, 185, 129, 0.16)', labelBg: 'rgba(4, 120, 87, 0.92)', text: '#ffffff' },
    { id: 'rose', name: 'Rose', stroke: '#f43f5e', fill: 'rgba(244, 63, 94, 0.16)', labelBg: 'rgba(190, 18, 60, 0.92)', text: '#ffffff' },
  ];

  const DEFAULT_VISIBILITY = Object.freeze({
    bboxes: true, track_ids: true, dwell_timers: true,
    velocity: false, zones: true, tripwires: true, heatmap: false,
  });

  function unpackTransform(t) {
    return { ox: t?.offsetX || 0, oy: t?.offsetY || 0, sx: t?.scaleX || 1, sy: t?.scaleY || 1 };
  }

  function computeContainBox(elemRect, containerRect, mediaWidth, mediaHeight) {
    const mw = Number(mediaWidth) > 0 ? Number(mediaWidth) : 1;
    const mh = Number(mediaHeight) > 0 ? Number(mediaHeight) : 1;
    const ew = Number(elemRect?.width) > 0 ? Number(elemRect.width) : mw;
    const eh = Number(elemRect?.height) > 0 ? Number(elemRect.height) : mh;
    const mediaAspect = mw / mh;
    const elemAspect = ew / eh;
    let renderW, renderH, renderLeft, renderTop;
    if (elemAspect > mediaAspect) {
      renderH = eh; renderW = renderH * mediaAspect;
      renderLeft = (ew - renderW) / 2; renderTop = 0;
    } else {
      renderW = ew; renderH = renderW / mediaAspect;
      renderLeft = 0; renderTop = (eh - renderH) / 2;
    }
    const baseLeft = containerRect ? (elemRect.left - containerRect.left) : 0;
    const baseTop = containerRect ? (elemRect.top - containerRect.top) : 0;
    return { offsetX: baseLeft + renderLeft, offsetY: baseTop + renderTop, renderW, renderH, scale: renderW / mw };
  }

  function computeCoverBox(elemRect, containerRect, mediaWidth, mediaHeight) {
    const mw = Number(mediaWidth) > 0 ? Number(mediaWidth) : 1;
    const mh = Number(mediaHeight) > 0 ? Number(mediaHeight) : 1;
    const ew = Number(elemRect?.width) > 0 ? Number(elemRect.width) : mw;
    const eh = Number(elemRect?.height) > 0 ? Number(elemRect.height) : mh;
    const scale = Math.max(ew / mw, eh / mh);
    const renderW = mw * scale;
    const renderH = mh * scale;
    const baseLeft = containerRect ? (elemRect.left - containerRect.left) : 0;
    const baseTop = containerRect ? (elemRect.top - containerRect.top) : 0;
    return { offsetX: baseLeft + (ew - renderW) / 2, offsetY: baseTop + (eh - renderH) / 2, renderW, renderH, scale };
  }

  function syncCanvasDpr(canvas, ctx, cssWidth, cssHeight, dpr, options = {}) {
    if (!canvas) return 1;
    const ratio = Number(dpr) > 0 ? Number(dpr) : (window.devicePixelRatio || 1);
    const w = Math.max(0, Number(cssWidth) || 0);
    const h = Math.max(0, Number(cssHeight) || 0);
    const pixelW = Math.round(w * ratio);
    const pixelH = Math.round(h * ratio);
    if (canvas.width !== pixelW || canvas.height !== pixelH) {
      canvas.width = pixelW; canvas.height = pixelH;
    }
    if (canvas.style) {
      canvas.style.width = options?.responsive ? '' : `${w}px`;
      canvas.style.height = options?.responsive ? '' : `${h}px`;
    }
    if (ctx && typeof ctx.setTransform === 'function') ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    return ratio;
  }

  function resolveScaleFactors(renderW, renderH, sourceRes, mediaWidth, mediaHeight) {
    const hasSrc = Array.isArray(sourceRes) && sourceRes.length >= 2;
    const srcW = hasSrc && Number(sourceRes[0]) > 0 ? Number(sourceRes[0]) : (Number(mediaWidth) || 1);
    const srcH = hasSrc && Number(sourceRes[1]) > 0 ? Number(sourceRes[1]) : (Number(mediaHeight) || 1);
    return { scaleX: renderW / srcW, scaleY: renderH / srcH };
  }

  function drawLabelPill(ctx, text, x, y, palette) {
    ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    const pad = 4;
    const bgW = (ctx.measureText(text)?.width || text.length * 6) + (pad * 2);
    ctx.fillStyle = palette?.labelBg || 'rgba(8, 145, 178, 0.92)';
    ctx.fillRect(x, y, bgW, 18);
    ctx.fillStyle = palette?.text || '#ffffff';
    ctx.textBaseline = 'top';
    ctx.fillText(text, x + pad, y + 2);
  }

  function buildTrackLabel(track, vis, labelPrefix) {
    const base = track.entity_name || track.identity_label || track.label || 'object';
    const parts = [String(labelPrefix || '') + base];
    if (track.confidence != null) parts.push(`${(Number(track.confidence) * 100).toFixed(0)}%`);
    const tid = track.id ?? track.track_id;
    if (vis.track_ids && tid != null) parts.push(`#${tid}`);
    if (vis.dwell_timers && track.dwell_time != null) parts.push(`${Number(track.dwell_time).toFixed(1)}s`);
    return parts.join(' ');
  }

  function drawTrackBox(ctx, track, transform, options = {}) {
    if (!ctx || !track?.bbox || track.bbox.length < 4) return;
    const vis = { ...DEFAULT_VISIBILITY, ...(options.visibility || {}) };
    const palette = options.palette || PALETTES[0];
    const { ox, oy, sx, sy } = unpackTransform(transform);
    const [bx, by, bw, bh] = track.bbox;
    const x = ox + (bx * sx), y = oy + (by * sy), w = bw * sx, h = bh * sy;
    if (vis.bboxes) {
      ctx.save();
      ctx.strokeStyle = palette.stroke || '#06b6d4';
      ctx.lineWidth = options.isHovered ? 3 : 2;
      if (options.isHovered) { ctx.shadowColor = palette.stroke || '#06b6d4'; ctx.shadowBlur = 12; }
      ctx.fillStyle = palette.fill || 'rgba(6, 182, 212, 0.16)';
      ctx.fillRect(x, y, w, h);
      ctx.strokeRect(x, y, w, h);
      ctx.restore();
    }
    if (vis.track_ids || vis.dwell_timers) {
      drawLabelPill(ctx, buildTrackLabel(track, vis, options.labelPrefix), x, Math.max(oy, y - 18), palette);
    }
  }

  function drawVelocityVector(ctx, track, transform, palette = PALETTES[0]) {
    if (!ctx || !Array.isArray(track?.velocity) || track.velocity.length < 2) return;
    const [vx, vy] = track.velocity;
    if (Math.hypot(vx, vy) < 0.25) return;
    const { ox, oy, sx, sy } = unpackTransform(transform);
    const cx = Array.isArray(track.centroid) ? track.centroid[0] : (track.bbox[0] + track.bbox[2] / 2);
    const cy = Array.isArray(track.centroid) ? track.centroid[1] : (track.bbox[1] + track.bbox[3] / 2);
    const x1 = ox + (cx * sx), y1 = oy + (cy * sy);
    const x2 = x1 + (vx * sx * 0.4), y2 = y1 + (vy * sy * 0.4);
    const angle = Math.atan2(y2 - y1, x2 - x1);
    ctx.save();
    ctx.strokeStyle = palette.stroke || '#f59e0b';
    ctx.fillStyle = palette.stroke || '#f59e0b';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - 7 * Math.cos(angle - 0.5), y2 - 7 * Math.sin(angle - 0.5));
    ctx.lineTo(x2 - 7 * Math.cos(angle + 0.5), y2 - 7 * Math.sin(angle + 0.5));
    ctx.closePath(); ctx.fill();
    ctx.restore();
  }

  function drawZones(ctx, zones, transform) {
    if (!ctx || !Array.isArray(zones)) return;
    const { ox, oy, sx, sy } = unpackTransform(transform);
    zones.forEach((zone) => {
      const pts = zone?.polygon || zone?.points;
      if (!Array.isArray(pts) || pts.length < 3) return;
      const breached = Boolean(zone.is_breached);
      ctx.save();
      ctx.beginPath();
      pts.forEach((pt, idx) => (idx === 0 ? ctx.moveTo(ox + pt[0] * sx, oy + pt[1] * sy) : ctx.lineTo(ox + pt[0] * sx, oy + pt[1] * sy)));
      ctx.closePath();
      ctx.fillStyle = breached ? 'rgba(244, 63, 94, 0.22)' : 'rgba(16, 185, 129, 0.14)';
      ctx.strokeStyle = breached ? '#f43f5e' : '#10b981';
      ctx.lineWidth = 2;
      ctx.fill(); ctx.stroke();
      const label = `${zone.name || 'Zone'}${zone.occupancy != null ? ` (${zone.occupancy})` : ''}`;
      drawLabelPill(ctx, label, ox + pts[0][0] * sx, oy + pts[0][1] * sy, { labelBg: breached ? 'rgba(190, 18, 60, 0.9)' : 'rgba(4, 120, 87, 0.9)' });
      ctx.restore();
    });
  }

  function drawTripwires(ctx, tripwires, transform) {
    if (!ctx || !Array.isArray(tripwires)) return;
    const { ox, oy, sx, sy } = unpackTransform(transform);
    tripwires.forEach((tw) => {
      const seg = tw?.line;
      if (!Array.isArray(seg) || seg.length < 2) return;
      const p1 = Array.isArray(seg[0]) ? seg[0] : [seg[0], seg[1]];
      const p2 = Array.isArray(seg[1]) ? seg[1] : [seg[2], seg[3]];
      const x1 = ox + p1[0] * sx, y1 = oy + p1[1] * sy;
      const x2 = ox + p2[0] * sx, y2 = oy + p2[1] * sy;
      ctx.save();
      ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 2.5; ctx.setLineDash([6, 4]);
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      ctx.setLineDash([]);
      const counts = (tw.in_count != null || tw.out_count != null) ? ` ${tw.in_count || 0}/${tw.out_count || 0}` : '';
      drawLabelPill(ctx, `${tw.name || 'Tripwire'}${counts}`, (x1 + x2) / 2, (y1 + y2) / 2 - 9, PALETTES[1]);
      ctx.restore();
    });
  }

  function drawHeatmapLayer(ctx, heatmap, transform) {
    if (!ctx || !heatmap) return;
    const grid = Array.isArray(heatmap) ? heatmap : heatmap.grid;
    if (!Array.isArray(grid) || grid.length === 0 || !Array.isArray(grid[0])) return;
    const rows = grid.length, cols = grid[0].length;
    const maxVal = Number(heatmap.max) > 0 ? Number(heatmap.max) : 1;
    const cellW = (transform?.renderW || ctx.canvas?.width || cols) / cols;
    const cellH = (transform?.renderH || ctx.canvas?.height || rows) / rows;
    const { ox, oy } = unpackTransform(transform);
    ctx.save();
    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        const norm = Math.min(1, Math.max(0, Number(grid[r][c]) / maxVal));
        if (norm <= 0.02) continue;
        ctx.fillStyle = `rgba(239, 68, 68, ${(norm * 0.55).toFixed(3)})`;
        ctx.fillRect(ox + c * cellW, oy + r * cellH, cellW + 0.5, cellH + 0.5);
      }
    }
    ctx.restore();
  }

  function renderScene(ctx, scene = {}) {
    if (!ctx) return;
    const vis = { ...DEFAULT_VISIBILITY, ...(scene.visibility || {}) };
    const transform = scene.transform || { offsetX: 0, offsetY: 0, scaleX: 1, scaleY: 1 };
    if (scene.clear !== false && scene.clearWidth && scene.clearHeight) {
      ctx.clearRect(0, 0, scene.clearWidth, scene.clearHeight);
    }
    if (vis.heatmap && scene.heatmap) drawHeatmapLayer(ctx, scene.heatmap, transform);
    if (vis.zones && scene.zones) drawZones(ctx, scene.zones, transform);
    if (vis.tripwires && scene.tripwires) drawTripwires(ctx, scene.tripwires, transform);
    if (Array.isArray(scene.tracks)) {
      const hoveredId = scene.hoveredTrack ? (scene.hoveredTrack.id ?? scene.hoveredTrack.track_id) : null;
      scene.tracks.forEach((track) => {
        const tid = track.id ?? track.track_id;
        const isHovered = hoveredId != null && tid === hoveredId;
        if (vis.bboxes || vis.track_ids || vis.dwell_timers) {
          drawTrackBox(ctx, track, transform, {
            visibility: vis, palette: scene.palette || PALETTES[0],
            labelPrefix: scene.labelPrefix || '', isHovered,
          });
        }
        if (vis.velocity) drawVelocityVector(ctx, track, transform, scene.palette || PALETTES[0]);
      });
    }
  }

  window.UnifiedCanvasOverlay = {
    PALETTES, DEFAULT_VISIBILITY, computeContainBox, computeCoverBox, syncCanvasDpr,
    resolveScaleFactors, drawTrackBox, drawVelocityVector, drawZones,
    drawTripwires, drawHeatmapLayer, renderScene,
  };
})();
