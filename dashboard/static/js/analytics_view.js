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

    const ctx = chartCanvas.getContext('2d');
    trafficChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: ['-30s', '-25s', '-20s', '-15s', '-10s', '-5s', 'Now'],
        datasets: [
          {
            label: 'Tripwire Inflow',
            data: [0, 1, 2, 2, 4, 5, 7],
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            fill: true,
            tension: 0.35,
          },
          {
            label: 'Tripwire Outflow',
            data: [0, 0, 1, 1, 2, 3, 4],
            borderColor: '#f59e0b',
            backgroundColor: 'rgba(245, 158, 11, 0.1)',
            fill: true,
            tension: 0.35,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#94a3b8', font: { family: 'Inter' } } }
        },
        scales: {
          x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' } },
          y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' }, beginAtZero: true }
        }
      }
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

  async function loadAlertsTable() {
    const tbody = document.getElementById('alerts-table-body');
    const badge = document.getElementById('total-alerts-count');
    if (!tbody) return;

    try {
      const res = await fetch('/events?limit=50');
      const events = await res.json();
      if (badge) badge.textContent = `${events.length} event${events.length !== 1 ? 's' : ''}`;

      if (!events.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">No alerts logged yet.</td></tr>';
        return;
      }

      tbody.innerHTML = events.map(ev => {
        const timeStr = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleString() : '--';
        const type = ev.event_type || 'alert';
        let severityClass = 'panel-badge';
        let severityText = 'INFO';

        if (type.includes('intrusion') || type.includes('restricted')) {
          severityClass = 'badge-category restricted';
          severityText = 'CRITICAL';
        } else if (type.includes('threshold') || type.includes('capacity')) {
          severityClass = 'badge-category vip';
          severityText = 'WARNING';
        }

        const snapshotBtn = ev.snapshot_base64
          ? `<button class="btn btn-xs btn-outline" onclick="window.showSnapshotModal('data:image/jpeg;base64,${ev.snapshot_base64}', '${escapeHtml(type)}')">View</button>`
          : '<span class="text-subtle">None</span>';

        return `
          <tr>
            <td>${escapeHtml(timeStr)}</td>
            <td><strong>${escapeHtml(type)}</strong></td>
            <td><span class="${severityClass}">${severityText}</span></td>
            <td>${escapeHtml(ev.zone_id || ev.camera_id || 'System')}</td>
            <td>${escapeHtml(ev.entity_name || (ev.entity_id ? '#' + ev.entity_id : 'Unknown'))}</td>
            <td>${escapeHtml(JSON.stringify(ev.metadata || {}))}</td>
            <td>${snapshotBtn}</td>
          </tr>
        `;
      }).join('');
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

