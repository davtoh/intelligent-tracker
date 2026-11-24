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

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatRangeLabel(sec) {
    if (sec <= 900) return '15m';
    if (sec <= 3600) return '1h';
    if (sec <= 21600) return '6h';
    if (sec <= 86400) return '24h';
    return '7d';
  }

  function formatBucketLabel(bucketStart, fallbackLabel, spanSec) {
    if (!Number.isFinite(Number(bucketStart))) return fallbackLabel || '';
    const d = new Date(Number(bucketStart) * 1000);
    if (spanSec > 86400) {
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' '
        + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function syncWindowControls(data) {
    const labelEl = document.getElementById('analytics-window-label');
    const nextBtn = document.getElementById('btn-analytics-next');
    const liveBtn = document.getElementById('btn-analytics-live');
    if (nextBtn) nextBtn.disabled = isLive;
    if (liveBtn) {
      liveBtn.disabled = isLive;
      liveBtn.classList.toggle('active', !isLive);
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

  async function loadTrafficFlows() {
    lastFlowRefreshAt = Date.now();
    const camId = window.App?.getActiveCameraId?.() || '';
    const params = new URLSearchParams({ range_sec: String(rangeSec) });
    if (camId) params.set('camera_id', camId);
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
    const camId = window.App?.getActiveCameraId?.() || '';
    const url = camId
      ? `/analytics/heatmap?format=json&camera_id=${encodeURIComponent(camId)}`
      : '/analytics/heatmap?format=json';
    try {
      const res = await fetch(url);
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
        const stopsCss = data.stops.map((s) => `${s.color} ${Math.round(Number(s.ratio || 0) * 100)}%`).join(', ');
        barEl.style.background = `linear-gradient(90deg, ${stopsCss})`;
      }
      if (metaEl) {
        if (data && data.initialized !== false && Array.isArray(data.resolution)) {
          const decayStr = data.decay_rate !== null && data.decay_rate !== undefined ? data.decay_rate : 'cumulative';
          metaEl.textContent = `${data.camera_id || 'All Cameras'} · ${data.colormap || 'JET'} · ${data.resolution[0]}x${data.resolution[1]} · r=${data.radius || 25}px · decay=${decayStr}`;
        } else {
          metaEl.textContent = `${data?.camera_id || 'All Cameras'} · Heatmap uninitialized`;
        }
      }
      window.AnalyticsDrilldown?.setHeatmapData?.(data);
      return data;
    } catch (err) {
      console.error('Heatmap metadata fetch error:', err);
      return null;
    }
  }

  function bindFlowControls() {
    const rangeSel = document.getElementById('analytics-range-select');
    const prevBtn = document.getElementById('btn-analytics-prev');
    const nextBtn = document.getElementById('btn-analytics-next');
    const liveBtn = document.getElementById('btn-analytics-live');
    if (rangeSel && !rangeSel.dataset.bound) {
      rangeSel.dataset.bound = '1';
      rangeSel.addEventListener('change', () => {
        rangeSec = Math.max(60, Number(rangeSel.value) || 3600);
        endTime = null;
        isLive = true;
        loadTrafficFlows();
      });
    }
    if (prevBtn && !prevBtn.dataset.bound) {
      prevBtn.dataset.bound = '1';
      prevBtn.addEventListener('click', () => {
        const nowSec = Math.floor(Date.now() / 1000);
        endTime = (isLive || endTime === null) ? (nowSec - rangeSec) : (endTime - rangeSec);
        isLive = false;
        loadTrafficFlows();
      });
    }
    if (nextBtn && !nextBtn.dataset.bound) {
      nextBtn.dataset.bound = '1';
      nextBtn.addEventListener('click', () => {
        if (isLive || endTime === null) return;
        const nowSec = Math.floor(Date.now() / 1000);
        const nextEnd = endTime + rangeSec;
        if (nextEnd >= nowSec) {
          endTime = null;
          isLive = true;
        } else {
          endTime = nextEnd;
        }
        loadTrafficFlows();
      });
    }
    if (liveBtn && !liveBtn.dataset.bound) {
      liveBtn.dataset.bound = '1';
      liveBtn.addEventListener('click', () => {
        endTime = null;
        isLive = true;
        loadTrafficFlows();
      });
    }
  }

  function initTrafficChart() {
    const chartCanvas = document.getElementById('trafficChart');
    if (!trafficChart && chartCanvas && typeof Chart !== 'undefined') {
      const gridStyle = { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' } };
      trafficChart = new Chart(chartCanvas.getContext('2d'), {
        type: 'line',
        data: {
          labels: [],
          datasets: [
            { label: 'Inflow (Entries / Crossings)', data: [], borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.1)', fill: true, tension: 0.35 },
            { label: 'Outflow (Exits / Crossings)', data: [], borderColor: '#f59e0b', backgroundColor: 'rgba(245, 158, 11, 0.1)', fill: true, tension: 0.35 },
          ],
        },
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
    loadTrafficFlows();
    loadHeatmapMetadata();
  }

  function updateTrafficChart() {
    if (!isLive) return;
    if (!document.getElementById('tab-analytics')?.classList?.contains('active')) return;
    if (Date.now() - lastFlowRefreshAt >= 5000) {
      loadTrafficFlows();
    }
  }

  function buildAlertRowHtml(ev) {
    const timeStr = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleString() : '--';
    const type = ev.event_type || 'alert';
    const rawSev = String(ev.severity || '').toUpperCase();
    let severityClass = 'panel-badge';
    let severityText = rawSev || 'INFO';
    if (rawSev === 'CRITICAL' || rawSev === 'HIGH' || (!rawSev && (type.includes('intrusion') || type.includes('restricted')))) {
      severityClass = 'badge-category restricted';
      severityText = rawSev || 'CRITICAL';
    } else if (rawSev === 'WARNING' || rawSev === 'MEDIUM' || (!rawSev && (type.includes('threshold') || type.includes('capacity')))) {
      severityClass = 'badge-category vip';
      severityText = rawSev || 'WARNING';
    }
    const entityLabel = ev.name || ev.entity_name || ev.suggested_name || (ev.entity_id ? '#' + ev.entity_id : 'Unknown');
    const detailText = ev.message || ev.reason || ev.title || ev.summary || JSON.stringify(ev.metadata || {});
    const snapshotBtn = ev.snapshot_base64
      ? `<button class="btn btn-xs btn-outline" onclick="window.showSnapshotModal('data:image/jpeg;base64,${ev.snapshot_base64}', '${escapeHtml(type)}')">View</button>`
      : '<span class="text-subtle">None</span>';
    const vFile = ev.video_filename || ev.metadata?.video_filename || '';
    const vOffset = ev.media_offset_sec ?? ev.metadata?.media_offset_sec ?? 0;
    const seekBtn = window.VideoTimelineLinks?.buildSeekInStudioButtonHtml(vFile, vOffset) || '';
    return `
      <tr>
        <td>${escapeHtml(timeStr)}</td><td><strong>${escapeHtml(type)}</strong></td>
        <td><span class="${severityClass}">${escapeHtml(severityText)}</span></td>
        <td>${escapeHtml(ev.zone_id || ev.camera_id || 'System')}</td>
        <td>${escapeHtml(entityLabel)}</td><td>${escapeHtml(detailText)}</td>
        <td>${snapshotBtn}${seekBtn}</td>
      </tr>`;
  }

  async function loadAlertsTable(opts) {
    if (window.AlertsView?.loadAlerts) {
      return window.AlertsView.loadAlerts(opts);
    }
    const tbody = document.getElementById('alerts-table-body');
    const badge = document.getElementById('total-alerts-count');
    if (!tbody) return;
    try {
      const camId = window.App?.getActiveCameraId?.();
      const url = camId ? `/events?limit=50&camera_id=${encodeURIComponent(camId)}` : '/events?limit=50';
      const res = await fetch(url);
      const events = await res.json();
      if (badge) badge.textContent = `${events.length} event${events.length !== 1 ? 's' : ''}`;
      tbody.innerHTML = events.length
        ? events.map(buildAlertRowHtml).join('')
        : '<tr><td colspan="7" class="text-center">No alerts logged yet.</td></tr>';
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center">Error loading events: ${escapeHtml(err.message)}</td></tr>`;
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
      } catch (err) {
        console.error('Heatmap toggle error:', err);
      }
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
    initChart: initTrafficChart,
    updateChart: updateTrafficChart,
    loadTrafficFlows,
    loadHeatmapMetadata,
    loadAlerts: loadAlertsTable,
    initHeatmap: initHeatmapControls,
  };
})();
