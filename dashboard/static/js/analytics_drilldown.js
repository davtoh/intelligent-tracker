/**
 * Intelligent Tracker - Analytics Peak & Heatmap Hotspot Drill-Down.
 * Handles Chart.js flow peak click -> #timeline/#alerts drill-down and
 * 32x24 spatial heatmap grid hover tooltips + hotspot click drill-down.
 */
(function () {
  'use strict';

  const state = {
    flowData: null,
    heatmapData: null,
    hoveredCell: null,
    lastDrilldown: null,
  };

  function getGridDims(data) {
    const gs = Array.isArray(data?.grid_size) && data.grid_size.length >= 2 ? data.grid_size : [32, 24];
    const cols = Math.max(1, Number(gs[0]) || 32);
    const rows = Math.max(1, Number(gs[1]) || 24);
    return { cols, rows };
  }

  function getCssDimensions(canvas) {
    const rect = typeof canvas?.getBoundingClientRect === 'function' ? canvas.getBoundingClientRect() : null;
    const styleW = parseFloat(canvas?.style?.width || '');
    const styleH = parseFloat(canvas?.style?.height || '');
    const cssW = (rect && rect.width > 0) ? rect.width : (Number.isFinite(styleW) && styleW > 0 ? styleW : (canvas?.clientWidth || 320));
    const cssH = (rect && rect.height > 0) ? rect.height : (Number.isFinite(styleH) && styleH > 0 ? styleH : (canvas?.clientHeight || 240));
    const left = rect ? (rect.left || 0) : 0;
    const top = rect ? (rect.top || 0) : 0;
    return { cssW: Math.max(1, cssW), cssH: Math.max(1, cssH), left, top };
  }

  function resolveCellFromPointer(canvas, clientX, clientY) {
    if (!canvas) return null;
    const { cols, rows } = getGridDims(state.heatmapData);
    const { cssW, cssH, left, top } = getCssDimensions(canvas);
    const relX = Math.max(0, Math.min(0.999999, (Number(clientX) - left) / cssW));
    const relY = Math.max(0, Math.min(0.999999, (Number(clientY) - top) / cssH));
    const col = Math.floor(relX * cols);
    const row = Math.floor(relY * rows);
    const grid = Array.isArray(state.heatmapData?.grid) ? state.heatmapData.grid : [];
    const density = Number(grid[row]?.[col] ?? 0);
    const res = Array.isArray(state.heatmapData?.resolution) ? state.heatmapData.resolution : [0, 0];
    const px = res[0] ? Math.round(((col + 0.5) / cols) * Number(res[0])) : col;
    const py = res[1] ? Math.round(((row + 0.5) / rows) * Number(res[1])) : row;
    return { col, row, cols, rows, density, px, py, cssW, cssH, offsetX: relX * cssW, offsetY: relY * cssH };
  }

  function renderAxisTicks(data) {
    const xEl = document.getElementById('heatmap-axis-x');
    const yEl = document.getElementById('heatmap-axis-y');
    const xTicks = Array.isArray(data?.x_ticks) ? data.x_ticks : [];
    const yTicks = Array.isArray(data?.y_ticks) ? data.y_ticks : [];
    if (xEl) {
      xEl.innerHTML = xTicks.map((t) => `<span>${Number(t)}px</span>`).join('');
    }
    if (yEl) {
      yEl.innerHTML = yTicks.map((t) => `<span>${Number(t)}px</span>`).join('');
    }
  }

  function drawHotspotHighlight(canvas, cell) {
    if (!canvas || typeof canvas.getContext !== 'function') return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const { cssW, cssH } = getCssDimensions(canvas);
    if (window.UnifiedCanvasOverlay?.syncCanvasDpr) {
      window.UnifiedCanvasOverlay.syncCanvasDpr(canvas, ctx, cssW, cssH, window.devicePixelRatio || 1, { responsive: true });
    }
    ctx.clearRect(0, 0, cssW, cssH);
    if (!cell) return;
    const cellW = cssW / cell.cols;
    const cellH = cssH / cell.rows;
    ctx.save();
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.95)';
    ctx.fillStyle = `rgba(56, 189, 248, ${0.12 + cell.density * 0.25})`;
    ctx.lineWidth = 1.5;
    ctx.fillRect(cell.col * cellW, cell.row * cellH, cellW, cellH);
    ctx.strokeRect(cell.col * cellW, cell.row * cellH, cellW, cellH);
    ctx.restore();
  }

  function updateTooltip(cell, show) {
    const tip = document.getElementById('heatmap-hotspot-tooltip');
    if (!tip) return;
    if (!show || !cell) {
      tip.hidden = true;
      return;
    }
    const pct = Math.round(cell.density * 100);
    tip.textContent = `Cell (${cell.col},${cell.row}) · (${cell.px},${cell.py})px · ${pct}%`;
    tip.hidden = false;
    if (tip.style) {
      tip.style.left = `${Math.min(Math.max(4, cell.offsetX + 10), Math.max(4, cell.cssW - 150))}px`;
      tip.style.top = `${Math.max(4, cell.offsetY - 26)}px`;
    }
  }

  function normalizeNavMediaRef(rawRef, fallbackSource) {
    if (!rawRef || typeof rawRef !== 'object') return fallbackSource ? { source: fallbackSource } : {};
    const src = rawRef.source_ref && typeof rawRef.source_ref === 'object' ? rawRef.source_ref : rawRef;
    const ref = {};
    if (src.kind) ref.kind = src.kind;
    const camId = src.cameraId || src.camera_id || src.camera || '';
    if (camId) ref.cameraId = camId;
    const videoFn = src.videoFilename || src.video_filename || src.video || '';
    if (videoFn) ref.videoFilename = videoFn;
    const runId = src.runId || src.run_id || '';
    if (runId) ref.runId = runId;
    const offsetSec = src.mediaOffsetSec ?? src.media_offset_sec ?? src.offset_sec;
    if (offsetSec !== undefined && offsetSec !== null && Number.isFinite(Number(offsetSec))) ref.mediaOffsetSec = Number(offsetSec);
    if (src.ts !== undefined && src.ts !== null && Number.isFinite(Number(src.ts))) ref.ts = Number(src.ts);
    const trackId = src.trackId ?? src.track_id;
    if (trackId !== undefined && trackId !== null && Number.isFinite(Number(trackId))) ref.trackId = Number(trackId);
    const entityId = src.entityId ?? src.entity_id;
    if (entityId !== undefined && entityId !== null && entityId !== '') ref.entityId = entityId;
    const zoneId = src.zoneId || src.zone_id || '';
    if (zoneId) ref.zoneId = zoneId;
    if (Array.isArray(src.bbox) && src.bbox.length >= 4) ref.bbox = src.bbox.slice(0, 4);
    if (fallbackSource) ref.source = fallbackSource;
    return ref;
  }

  function drillDownToTimeWindow(bucket, targetTab = 'tab-timeline') {
    if (!bucket) return null;
    const bStart = Number(bucket.bucket_start);
    const bSec = Number(state.flowData?.bucket_sec || 60);
    const bEnd = Number.isFinite(Number(bucket.bucket_end)) ? Number(bucket.bucket_end) : (bStart + bSec);
    const camId = state.flowData?.camera_id || window.AnalyticsView?.getSelectedSource?.()?.id || window.App?.getActiveCameraId?.() || '';
    const firstMedia = Array.isArray(bucket.media_refs) && bucket.media_refs.length ? bucket.media_refs[0] : state.flowData?.source_ref;
    const navRef = { ...normalizeNavMediaRef(firstMedia, camId), startTime: bStart, endTime: bEnd, from: bStart, to: bEnd, offset: 0 };
    const record = {
      type: 'flow_peak',
      targetTab,
      cameraId: camId,
      startTime: bStart,
      endTime: bEnd,
      inflow: Number(bucket.inflow || 0),
      outflow: Number(bucket.outflow || 0),
      sourceRef: navRef,
    };
    state.lastDrilldown = record;
    const navFn = window.App?.navigate || window.AppNavigation?.navigate;
    if (navFn) {
      navFn(targetTab, navRef);
    } else {
      window.switchTab?.(targetTab);
      if (targetTab === 'tab-alerts') {
        window.AlertsView?.loadAlerts?.({ offset: 0, filters: { camera_id: camId, start_time: bStart, end_time: bEnd } });
      } else if (window.TimelineView?.applyFilter) {
        window.TimelineView.applyFilter({ source: camId, startTime: bStart, endTime: bEnd, offset: 0 });
      } else {
        window.GalleryTimeline?.loadSightings?.({ resetOffset: true });
      }
    }
    window.showToast?.('Flow Peak Drill-Down', `Filtered ${camId || 'All Cameras'} (${bucket.label || ''})`, 'info');
    return record;
  }

  function handleChartClick(evt, elements) {
    const idx = Array.isArray(elements) && elements.length > 0 ? elements[0]?.index : null;
    const buckets = Array.isArray(state.flowData?.buckets) ? state.flowData.buckets : [];
    if (idx === null || idx === undefined || !buckets[idx]) return null;
    const targetTab = evt?.native?.shiftKey ? 'tab-alerts' : 'tab-timeline';
    return drillDownToTimeWindow(buckets[idx], targetTab);
  }

  function handleHeatmapClick(canvas, clientX, clientY) {
    const cell = resolveCellFromPointer(canvas, clientX, clientY);
    if (!cell) return null;
    const camId = state.heatmapData?.camera_id || window.AnalyticsView?.getSelectedSource?.()?.id || window.App?.getActiveCameraId?.() || '';
    const hotspots = Array.isArray(state.heatmapData?.hotspots) ? state.heatmapData.hotspots : [];
    const matched = hotspots.find((h) => Number(h?.col) === cell.col && Number(h?.row) === cell.row);
    const peak = state.heatmapData?.peak_media_ref;
    const rawRef = matched || (peak && Number(peak.col) === cell.col && Number(peak.row) === cell.row ? peak : null) || state.heatmapData?.source_ref;
    const navRef = { ...normalizeNavMediaRef(rawRef, camId), offset: 0 };
    const record = {
      type: 'heatmap_cell',
      targetTab: 'tab-timeline',
      cameraId: camId,
      cellX: cell.col,
      cellY: cell.row,
      px: cell.px,
      py: cell.py,
      density: cell.density,
      sourceRef: navRef,
    };
    state.lastDrilldown = record;
    const navFn = window.App?.navigate || window.AppNavigation?.navigate;
    if (navFn) {
      navFn('tab-timeline', navRef);
    } else {
      window.switchTab?.('tab-timeline');
      if (window.TimelineView?.applyFilter) {
        window.TimelineView.applyFilter({ source: camId, offset: 0 });
      } else {
        window.GalleryTimeline?.loadSightings?.({ resetOffset: true });
      }
    }
    window.showToast?.('Hotspot Drill-Down', `Cell (${cell.col},${cell.row}) · ${Math.round(cell.density * 100)}% density`, 'info');
    return record;
  }

  function bindHeatmapCanvas() {
    const canvas = document.getElementById('heatmap-hotspot-canvas');
    if (!canvas || canvas.dataset?.bound) return;
    if (canvas.dataset) canvas.dataset.bound = '1';
    canvas.addEventListener('mousemove', (e) => {
      const cell = resolveCellFromPointer(canvas, e.clientX, e.clientY);
      state.hoveredCell = cell;
      drawHotspotHighlight(canvas, cell);
      updateTooltip(cell, true);
    });
    canvas.addEventListener('mouseleave', () => {
      state.hoveredCell = null;
      drawHotspotHighlight(canvas, null);
      updateTooltip(null, false);
    });
    canvas.addEventListener('click', (e) => {
      handleHeatmapClick(canvas, e.clientX, e.clientY);
    });
  }

  function setFlowData(data) {
    state.flowData = data || null;
  }

  function setHeatmapData(data) {
    state.heatmapData = data || null;
    renderAxisTicks(data);
    bindHeatmapCanvas();
  }

  window.AnalyticsDrilldown = {
    state,
    setFlowData,
    setHeatmapData,
    handleChartClick,
    handleHeatmapClick,
    resolveCellFromPointer,
    drillDownToTimeWindow,
    bindHeatmapCanvas,
  };
})();
