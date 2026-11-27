/**
 * Intelligent Tracker - Analytics, Traffic Chart & Heatmap Submodule.
 * Handles Chart.js time-bucketed ingress/egress flows, range navigation, and heatmap metadata.
 */

(function () {
  'use strict';

  let trafficChart = null;
  let rangeSec = 3600;
  let endTime = null;
  let isLive = true;
  let lastFlowRefreshAt = 0;
  let bucketPage = 1;
  let bucketPageSize = null;

  function escapeHtml(str) {
    return str ? String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;') : '';
  }

  function formatRangeLabel(sec) {
    return sec <= 900 ? '15m' : sec <= 3600 ? '1h' : sec <= 21600 ? '6h' : sec <= 86400 ? '24h' : '7d';
  }

  function formatBucketLabel(bucketStart, fallbackLabel, spanSec) {
    if (!Number.isFinite(Number(bucketStart))) return fallbackLabel || '';
    const d = new Date(Number(bucketStart) * 1000);
    const t = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return spanSec > 86400 ? `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${t}` : t;
  }

  function syncWindowControls(data) {
    const labelEl = document.getElementById('analytics-window-label');
    const pageEl = document.getElementById('analytics-bucket-page-summary');
    const nextBtn = document.getElementById('btn-analytics-next');
    const liveBtn = document.getElementById('btn-analytics-live');
    if (nextBtn) nextBtn.disabled = isLive;
    if (liveBtn) {
      liveBtn.disabled = isLive;
      liveBtn.classList.toggle('active', !isLive);
    }
    if (pageEl) {
      const pg = data?.pagination;
      const shown = Array.isArray(data?.buckets) ? data.buckets.length : 0;
      const total = Number(pg?.total_buckets ?? shown);
      const curPage = Number(pg?.page ?? 1);
      const totalPages = Math.max(1, Number(pg?.total_pages ?? 1));
      pageEl.textContent = totalPages > 1
        ? `Page ${curPage}/${totalPages} · ${shown}/${total} buckets`
        : `${total} bucket${total !== 1 ? 's' : ''}`;
    }
    if (!labelEl) return;
    const totals = data?.totals || {};
    const summary = `In ${totals.inflow || 0} / Out ${totals.outflow || 0}`;
    if (isLive) {
      labelEl.textContent = `Live · Last ${formatRangeLabel(rangeSec)} (${summary})`;
    } else if (data?.start_time && data?.end_time) {
      const sStr = new Date(data.start_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const eStr = new Date(data.end_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      labelEl.textContent = `Window · ${sStr}–${eStr} (${summary})`;
    }
  }

  function resolveAnalyticsSource() {
    const sel = document.getElementById('analytics-source-select');
    const selVal = sel?.value ? String(sel.value).trim() : '';
    if (selVal) {
      const ref = window.ActiveSourceContext?.fromSelectValue?.(selVal, sel)
        || (selVal.startsWith('video:') ? { kind: 'video', videoFilename: selVal.slice(6), cameraId: '' } : { kind: 'camera', cameraId: selVal, videoFilename: '' });
      return { id: ref.videoFilename || ref.cameraId || '', kind: ref.kind || 'camera', ref };
    }
    if (sel?.dataset?.userSelected === '1') return { id: '', kind: '', ref: null };
    const ctxRef = window.ActiveSourceContext?.get?.();
    if (ctxRef?.videoFilename) return { id: ctxRef.videoFilename, kind: 'video', ref: ctxRef };
    if (ctxRef?.cameraId) return { id: ctxRef.cameraId, kind: 'camera', ref: ctxRef };
    const fallback = window.App?.getActiveCameraId?.() || '';
    return { id: fallback, kind: fallback ? 'camera' : '', ref: fallback ? { kind: 'camera', cameraId: fallback } : null };
  }

  function syncHeatmapBadgeAndLink(src) {
    const badge = document.getElementById('heatmap-camera-badge');
    const dlBtn = document.getElementById('btn-download-heatmap');
    if (badge) badge.textContent = src.id ? `${src.kind === 'video' ? 'Video' : 'Camera'}: ${src.id}` : 'All Cameras';
    if (dlBtn) dlBtn.href = src.id ? `/analytics/heatmap?camera_id=${encodeURIComponent(src.id)}` : '/analytics/heatmap';
  }

  async function populateZoneFilter() {
    const sel = document.getElementById('analytics-zone-select');
    if (!sel) return;
    try {
      const res = await fetch('/zones');
      if (!res?.ok) return;
      const zones = await res.json();
      const prev = sel.value || '';
      const opts = ['<option value="">All Zones</option>'];
      (Array.isArray(zones) ? zones : []).forEach((z) => {
        const name = String(z?.name || z?.zone_id || '').trim();
        if (name) opts.push(`<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`);
      });
      sel.innerHTML = opts.join('');
      if (prev) sel.value = prev;
    } catch (_err) {
      // Keep default All Zones option when /zones is unavailable
    }
  }

  async function initSourceSelect() {
    const sel = document.getElementById('analytics-source-select');
    if (!sel || !window.ActiveSourceContext?.populateSelect) return null;
    const catalog = await window.ActiveSourceContext.populateSelect(sel, { includeAll: true, allLabel: 'All Sources' });
    const syncSelectTitle = () => {
      sel.title = sel.options?.[sel.selectedIndex]?.text || sel.value || 'All Sources';
    };
    if (!sel.dataset.sourceBound) {
      sel.dataset.sourceBound = '1';
      sel.addEventListener('change', () => {
        sel.dataset.userSelected = '1';
        bucketPage = 1;
        syncSelectTitle();
        const ref = window.ActiveSourceContext?.fromSelectValue?.(sel.value, sel) || null;
        if (ref) window.ActiveSourceContext?.set?.(ref);
        loadTrafficFlows();
        loadHeatmapMetadata();
        window.LivePlayer?.attachHeatmapImage?.(document.getElementById('static-heatmap-img'));
      });
    }
    syncSelectTitle();
    const src = resolveAnalyticsSource();
    syncHeatmapBadgeAndLink(src);
    if (src.ref) {
      const avail = window.ActiveSourceContext.checkAvailability(src.ref, catalog);
      if (!avail.available) window.ActiveSourceContext.showUnavailable(document.getElementById('static-heatmap-img'), avail);
    }
    return catalog;
  }

  async function loadTrafficFlows(opts = {}) {
    lastFlowRefreshAt = Date.now();
    if (opts && typeof opts.page === 'number') bucketPage = Math.max(1, opts.page);
    if (opts && opts.pageSize !== undefined) bucketPageSize = opts.pageSize;
    const src = resolveAnalyticsSource();
    const camParam = src.kind === 'video' && src.id ? `video:${src.id}` : src.id;
    const zoneId = String(document.getElementById('analytics-zone-select')?.value || '').trim();
    const eventType = String(document.getElementById('analytics-event-type-select')?.value || '').trim();
    const params = new URLSearchParams({ range_sec: String(rangeSec) });
    if (camParam) params.set('camera_id', camParam);
    if (zoneId) params.set('zone_id', zoneId);
    if (eventType) params.set('event_type', eventType);
    if (bucketPageSize) {
      params.set('page', String(bucketPage));
      params.set('page_size', String(bucketPageSize));
    }
    if (!isLive && endTime !== null) params.set('end_time', String(endTime));
    try {
      const res = await fetch(`/analytics/flows?${params.toString()}`);
      const data = await res.json();
      const buckets = Array.isArray(data?.buckets) ? data.buckets : [];
      if (trafficChart) {
        trafficChart.data.labels = buckets.map((b) => formatBucketLabel(b.bucket_start, b.label, rangeSec));
        trafficChart.data.datasets[0].data = buckets.map((b) => Number(b.inflow || 0));
        trafficChart.data.datasets[1].data = buckets.map((b) => Number(b.outflow || 0));
        if (data?.axes?.x?.label && trafficChart.options?.scales?.x?.title) {
          trafficChart.options.scales.x.title.text = `${data.axes.x.label} (Click peak to drill down)`;
        }
        if (data?.axes?.y?.label && trafficChart.options?.scales?.y?.title) {
          trafficChart.options.scales.y.title.text = data.axes.y.label;
        }
        trafficChart.update('none');
      }
      window.AnalyticsDrilldown?.setFlowData?.(data);
      syncWindowControls(data);
      return data;
    } catch (err) {
      console.error('Traffic flows fetch error:', err);
      return null;
    }
  }

  async function loadHeatmapMetadata() {
    const src = resolveAnalyticsSource();
    const camId = src.id;
    syncHeatmapBadgeAndLink(src);
    const url = camId ? `/analytics/heatmap?format=json&camera_id=${encodeURIComponent(camId)}` : '/analytics/heatmap?format=json';
    try {
      const res = await fetch(url);
      if (!res.ok) {
        window.MediaEmptyState?.showEmpty?.(document.getElementById('static-heatmap-img'), 'Heatmap Unavailable', camId ? `No live heatmap for '${camId}'.` : 'Heatmap unavailable.');
        return null;
      }
      const data = await res.json();
      const minEl = document.getElementById('heatmap-legend-min');
      const midEl = document.getElementById('heatmap-legend-mid');
      const maxEl = document.getElementById('heatmap-legend-max');
      const metaEl = document.getElementById('heatmap-meta-summary');
      const barEl = document.querySelector('#heatmap-colorbar-legend .heatmap-colorbar');
      const maxVal = Number(data?.max_value || 0);
      if (minEl) minEl.textContent = '0.00';
      if (midEl) midEl.textContent = (maxVal * 0.5).toFixed(2);
      if (maxEl) maxEl.textContent = maxVal.toFixed(2);
      if (barEl && Array.isArray(data?.stops) && data.stops.length >= 2) {
        barEl.style.background = `linear-gradient(90deg, ${data.stops.map((s) => `${s.color} ${Math.round(Number(s.ratio || 0) * 100)}%`).join(', ')})`;
      }
      if (metaEl) {
        const decayStr = data?.decay_rate !== null && data?.decay_rate !== undefined ? data.decay_rate : 'cumulative';
        metaEl.textContent = (data && data.initialized !== false && Array.isArray(data.resolution))
          ? `${data.camera_id || 'All Cameras'} · ${data.colormap || 'JET'} · ${data.resolution[0]}x${data.resolution[1]} · r=${data.radius || 25}px · decay=${decayStr}`
          : `${data?.camera_id || 'All Cameras'} · Heatmap uninitialized`;
      }
      window.AnalyticsDrilldown?.setHeatmapData?.(data);
      return data;
    } catch (err) {
      console.error('Heatmap metadata fetch error:', err);
      return null;
    }
  }

  function bindOnce(id, ev, fn) {
    const el = document.getElementById(id);
    if (el && !el.dataset?.bound) {
      if (el.dataset) el.dataset.bound = '1';
      el.addEventListener(ev, fn);
    }
  }

  function bindFlowControls() {
    bindOnce('analytics-range-select', 'change', () => {
      rangeSec = Math.max(60, Number(document.getElementById('analytics-range-select')?.value) || 3600);
      endTime = null; isLive = true; bucketPage = 1; loadTrafficFlows();
    });
    bindOnce('analytics-zone-select', 'change', () => { bucketPage = 1; loadTrafficFlows(); });
    bindOnce('analytics-event-type-select', 'change', () => { bucketPage = 1; loadTrafficFlows(); });
    bindOnce('btn-analytics-prev', 'click', () => {
      const nowSec = Math.floor(Date.now() / 1000);
      endTime = (isLive || endTime === null) ? (nowSec - rangeSec) : (endTime - rangeSec);
      isLive = false; bucketPage = 1; loadTrafficFlows();
    });
    bindOnce('btn-analytics-next', 'click', () => {
      if (isLive || endTime === null) return;
      const nowSec = Math.floor(Date.now() / 1000);
      const nextEnd = endTime + rangeSec;
      if (nextEnd >= nowSec) { endTime = null; isLive = true; } else { endTime = nextEnd; }
      bucketPage = 1; loadTrafficFlows();
    });
    bindOnce('btn-analytics-live', 'click', () => { endTime = null; isLive = true; bucketPage = 1; loadTrafficFlows(); });
  }

  function initTrafficChart() {
    const chartCanvas = document.getElementById('trafficChart');
    if (!trafficChart && chartCanvas && typeof Chart !== 'undefined') {
      const gridStyle = { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' } };
      trafficChart = new Chart(chartCanvas.getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [
          { label: 'Inflow (Entries / Crossings)', data: [], borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.1)', fill: true, tension: 0.35 },
          { label: 'Outflow (Exits / Crossings)', data: [], borderColor: '#f59e0b', backgroundColor: 'rgba(245, 158, 11, 0.1)', fill: true, tension: 0.35 },
        ] },
        options: {
          responsive: true, maintainAspectRatio: false,
          onClick: (evt, elements, chart) => window.AnalyticsDrilldown?.handleChartClick?.(evt, elements, chart),
          plugins: { legend: { labels: { color: '#94a3b8', font: { family: 'Inter' } } } },
          scales: {
            x: { ...gridStyle, title: { display: true, text: 'Time (Click peak to drill down)', color: '#94a3b8' } },
            y: { ...gridStyle, beginAtZero: true, title: { display: true, text: 'Crossings / Events', color: '#94a3b8' } },
          },
        },
      });
    }
    bindFlowControls();
    populateZoneFilter();
    if (window.ActiveSourceContext?.populateSelect && document.getElementById('analytics-source-select')) {
      initSourceSelect().then(() => { loadTrafficFlows(); loadHeatmapMetadata(); });
    } else {
      loadTrafficFlows();
      loadHeatmapMetadata();
    }
  }

  function updateTrafficChart() {
    if (!isLive) return;
    if (!document.getElementById('tab-analytics')?.classList?.contains('active')) return;
    if (Date.now() - lastFlowRefreshAt >= 5000) loadTrafficFlows();
  }

  async function loadAlertsTable(opts) {
    if (window.AlertsView?.loadAlerts) return window.AlertsView.loadAlerts(opts);
    const tbody = document.getElementById('alerts-table-body');
    const badge = document.getElementById('total-alerts-count');
    if (!tbody) return [];
    try {
      const camId = window.App?.getActiveCameraId?.();
      const res = await fetch(camId ? `/events?limit=50&camera_id=${encodeURIComponent(camId)}` : '/events?limit=50');
      const events = await res.json();
      if (badge) badge.textContent = `${events.length} event${events.length !== 1 ? 's' : ''}`;
      tbody.innerHTML = events.length ? events.map((ev) => {
        const seekBtn = window.VideoTimelineLinks?.buildSeekInStudioButtonHtml(ev.video_filename || ev.metadata?.video_filename || '', ev.media_offset_sec ?? ev.metadata?.media_offset_sec ?? 0) || '';
        const who = ev.name || ev.entity_name || ev.suggested_name || (ev.entity_id ? `#${ev.entity_id}` : 'Unknown');
        const msg = ev.message || ev.reason || ev.title || ev.summary || JSON.stringify(ev.metadata || {});
        return `<tr><td>${escapeHtml(ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleString() : '--')}</td><td><strong>${escapeHtml(ev.event_type || 'alert')}</strong></td><td><span class="panel-badge">${escapeHtml(String(ev.severity || 'INFO').toUpperCase())}</span></td><td>${escapeHtml(ev.zone_id || ev.camera_id || 'System')}</td><td>${escapeHtml(who)}</td><td>${escapeHtml(msg)}</td><td>${seekBtn}</td></tr>`;
      }).join('') : '<tr><td colspan="7" class="text-center">No alerts logged yet.</td></tr>';
      return events;
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center">Error loading events: ${escapeHtml(err.message)}</td></tr>`;
      return [];
    }
  }

  function initHeatmapControls() {
    let heatmapActive = false;
    const toggleBtn = document.getElementById('toggle-heatmap-btn');
    const refreshBtn = document.getElementById('btn-refresh-heatmap');
    toggleBtn?.addEventListener('click', async () => {
      try {
        const res = await fetch('/analytics/heatmap/toggle', { method: 'POST' });
        const data = await res.json();
        heatmapActive = data.draw_heatmap;
        toggleBtn.textContent = heatmapActive ? '🔥 Heatmap: ON' : '🔥 Heatmap: OFF';
        toggleBtn.classList.toggle('active', heatmapActive);
      } catch (err) { console.error('Heatmap toggle error:', err); }
    });
    refreshBtn?.addEventListener('click', () => {
      const img = document.getElementById('static-heatmap-img');
      if (window.LivePlayer?.attachHeatmapImage) window.LivePlayer.attachHeatmapImage(img);
      else if (img) img.src = `/analytics/heatmap?t=${Date.now()}`;
      loadHeatmapMetadata();
    });
    if (document.getElementById('tab-analytics')?.classList?.contains('active')) {
      window.LivePlayer?.attachHeatmapImage?.(document.getElementById('static-heatmap-img'));
      loadHeatmapMetadata();
    }
  }

  window.AnalyticsView = {
    initChart: initTrafficChart, updateChart: updateTrafficChart, loadTrafficFlows,
    loadHeatmapMetadata, loadAlerts: loadAlertsTable, initHeatmap: initHeatmapControls,
    initSourceSelect, getSelectedSource: resolveAnalyticsSource,
  };
})();
