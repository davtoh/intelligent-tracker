/**
 * Intelligent Tracker - Analytics, Traffic Chart & Heatmap Submodule.
 * Handles Chart.js real-time ingress/egress plotting, false-color density heatmaps, and alerts table.
 */

(function () {
  'use strict';

  let trafficChart = null;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function initTrafficChart() {
    if (trafficChart) return;
    const chartCanvas = document.getElementById('trafficChart');
    if (!chartCanvas || typeof Chart === 'undefined') return;
    const gridStyle = { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' } };
    trafficChart = new Chart(chartCanvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: ['-30s', '-25s', '-20s', '-15s', '-10s', '-5s', 'Now'],
        datasets: [
          { label: 'Tripwire Inflow', data: [0, 1, 2, 2, 4, 5, 7], borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.1)', fill: true, tension: 0.35 },
          { label: 'Tripwire Outflow', data: [0, 0, 1, 1, 2, 3, 4], borderColor: '#f59e0b', backgroundColor: 'rgba(245, 158, 11, 0.1)', fill: true, tension: 0.35 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#94a3b8', font: { family: 'Inter' } } } },
        scales: { x: gridStyle, y: { ...gridStyle, beginAtZero: true } },
      },
    });
  }

  function updateTrafficChart(totalCount) {
    if (!trafficChart) return;
    const nowLabel = new Date().toLocaleTimeString();
    if (trafficChart.data.labels.length > 15) {
      trafficChart.data.labels.shift();
      trafficChart.data.datasets[0].data.shift();
      trafficChart.data.datasets[1].data.shift();
    }
    trafficChart.data.labels.push(nowLabel);
    trafficChart.data.datasets[0].data.push(Math.round(totalCount * 0.6));
    trafficChart.data.datasets[1].data.push(Math.round(totalCount * 0.4));
    trafficChart.update('none');
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

  async function loadAlertsTable() {
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
      if (img) img.src = `/analytics/heatmap?t=${Date.now()}`;
    });
  }

  window.AnalyticsView = {
    initChart: initTrafficChart,
    updateChart: updateTrafficChart,
    loadAlerts: loadAlertsTable,
    initHeatmap: initHeatmapControls,
  };
})();

