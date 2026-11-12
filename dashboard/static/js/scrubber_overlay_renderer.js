/**
 * Intelligent Tracker - Scrubber Overlay Geometry & Canvas Renderer Helpers.
 *
 * Pure coordinate transformation, binary-search timestamp lookup, palette
 * definitions, and bounding-box drawing primitives for Video Scrubber layers.
 */

(function () {
  'use strict';

  const LAYER_PALETTES = [
    { id: 'cyan', name: 'Cyan', stroke: '#06b6d4', fill: 'rgba(6, 182, 212, 0.16)', labelBg: 'rgba(8, 145, 178, 0.92)', text: '#ffffff' },
    { id: 'amber', name: 'Amber', stroke: '#f59e0b', fill: 'rgba(245, 158, 11, 0.16)', labelBg: 'rgba(180, 83, 9, 0.92)', text: '#ffffff' },
    { id: 'purple', name: 'Purple', stroke: '#a855f7', fill: 'rgba(168, 85, 247, 0.16)', labelBg: 'rgba(126, 34, 206, 0.92)', text: '#ffffff' },
    { id: 'emerald', name: 'Emerald', stroke: '#10b981', fill: 'rgba(16, 185, 129, 0.16)', labelBg: 'rgba(4, 120, 87, 0.92)', text: '#ffffff' },
    { id: 'rose', name: 'Rose', stroke: '#f43f5e', fill: 'rgba(244, 63, 94, 0.16)', labelBg: 'rgba(190, 18, 60, 0.92)', text: '#ffffff' },
  ];

  /**
   * Find closest time-indexed detection record using binary search.
   * Allows up to tolerance seconds (default 0.35s) discrepancy for strided analysis.
   */
  function findClosestDetections(frameDetections, currentTime, tolerance = 0.35) {
    if (!Array.isArray(frameDetections) || frameDetections.length === 0) return null;
    let low = 0;
    let high = frameDetections.length - 1;

    while (low <= high) {
      const mid = (low + high) >> 1;
      const t = frameDetections[mid].time;
      if (t < currentTime) {
        low = mid + 1;
      } else if (t > currentTime) {
        high = mid - 1;
      } else {
        return frameDetections[mid];
      }
    }

    let best = null;
    let bestDiff = Infinity;
    [low, high].forEach((idx) => {
      if (idx >= 0 && idx < frameDetections.length) {
        const diff = Math.abs(frameDetections[idx].time - currentTime);
        if (diff < bestDiff) {
          bestDiff = diff;
          best = frameDetections[idx];
        }
      }
    });
    return bestDiff <= tolerance ? best : null;
  }

  /**
   * Compute rendered video rectangle inside object-fit: contain element box,
   * accounting for letterbox (top/bottom) or pillarbox (left/right) offsets.
   */
  function computeVideoRenderBox(vRect, vpRect, videoWidth, videoHeight) {
    const videoAspect = videoWidth / videoHeight;
    const elemAspect = vRect.width / vRect.height;
    let renderW, renderH, renderLeft, renderTop;

    if (elemAspect > videoAspect) {
      renderH = vRect.height;
      renderW = renderH * videoAspect;
      renderLeft = (vRect.width - renderW) / 2;
      renderTop = 0;
    } else {
      renderW = vRect.width;
      renderH = renderW / videoAspect;
      renderLeft = 0;
      renderTop = (vRect.height - renderH) / 2;
    }

    return {
      offsetX: (vRect.left - vpRect.left) + renderLeft,
      offsetY: (vRect.top - vpRect.top) + renderTop,
      renderW,
      renderH,
      scale: renderW / videoWidth,
    };
  }

  /**
   * Compute horizontal and vertical scale factors from source detection resolution
   * to the rendered video viewport box, preserving alignment across transcoded resolutions.
   */
  function resolveScaleFactors(renderW, renderH, record, videoWidth, videoHeight, fallbackSourceRes = null) {
    const srcRes = (Array.isArray(record?.source_resolution) && record.source_resolution.length >= 2)
      ? record.source_resolution
      : (Array.isArray(fallbackSourceRes) && fallbackSourceRes.length >= 2
          ? fallbackSourceRes
          : [videoWidth, videoHeight]);
    const srcW = Number(srcRes[0]) > 0 ? Number(srcRes[0]) : videoWidth;
    const srcH = Number(srcRes[1]) > 0 ? Number(srcRes[1]) : videoHeight;
    return {
      scaleX: renderW / srcW,
      scaleY: renderH / srcH,
    };
  }

  /**
   * Draw a single tracked bounding box and clamped label using the layer's color palette.
   */
  function drawTrackBox(ctx, track, offsetX, offsetY, scaleX, scaleY, palette = LAYER_PALETTES[0], labelPrefix = '') {
    if (!ctx || !track.bbox || track.bbox.length < 4) return;
    const [bx, by, bw, bh] = track.bbox;
    const x = offsetX + (bx * scaleX);
    const y = offsetY + (by * scaleY);
    const w = bw * scaleX;
    const h = bh * scaleY;

    ctx.strokeStyle = palette.stroke || '#06b6d4';
    ctx.lineWidth = 2;
    ctx.fillStyle = palette.fill || 'rgba(6, 182, 212, 0.16)';
    ctx.fillRect(x, y, w, h);
    ctx.strokeRect(x, y, w, h);

    const conf = track.confidence ? ` ${(track.confidence * 100).toFixed(0)}%` : '';
    const idTag = track.track_id != null ? ` #${track.track_id}` : '';
    const labelText = labelPrefix + (track.identity_label || track.label || 'object') + conf + idTag;

    ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    const textMetrics = ctx.measureText(labelText);
    const pad = 4;
    const bgWidth = textMetrics.width + (pad * 2);
    const bgHeight = 14 + pad;
    const labelY = Math.max(offsetY, y - bgHeight);

    ctx.fillStyle = palette.labelBg || 'rgba(8, 145, 178, 0.92)';
    ctx.fillRect(x, labelY, bgWidth, bgHeight);

    ctx.fillStyle = palette.text || '#ffffff';
    ctx.textBaseline = 'top';
    ctx.fillText(labelText, x + pad, labelY + 2);
  }

  window.ScrubberOverlayRenderer = {
    PALETTES: LAYER_PALETTES,
    findClosestDetections,
    computeVideoRenderBox,
    resolveScaleFactors,
    drawTrackBox,
  };
})();

