/**
 * Intelligent Tracker - Analytics, Heatmap & Security Alerts Controller (Tabs 4 & 5).
 * Renders real-time Chart.js traffic lines, heatmap updates, and alerts log table.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  const escapeHtml = window.escapeHtml || (s => s);
  let chart = null;

  function initTrafficChart() {
    if (chart) return;
    const chartCanvas = document.getElementById('trafficChart');
    if (!chartCanvas || typeof Chart === 'undefined') return;

    const ctxChart = chartCanvas.getContext('2d');
    chart = new Chart(ctxChart, {
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
    if (!chart) return;
    const nowLabel = new Date().toLocaleTimeString();
    if (chart.data.labels.length > 15) {
      chart.data.labels.shift();
      chart.data.datasets[0].data.shift();
      chart.data.datasets[1].data.shift();
    }
    chart.data.labels.push(nowLabel);
    chart.data.datasets[0].data.push(Math.round(totalCount * 0.6));
    chart.data.datasets[1].data.push(Math.round(totalCount * 0.4));
    chart.update('none');
  }

  async function loadAlertsTable() {
    const tbody = document.getElementById('alerts-table-body');
    const badge = document.getElementById('total-alerts-count');
    if (!tbody) return;

    try {
      const res = await fetch('/events?limit=50');
      const events = await res.json();
      if (badge) {
        badge.textContent = `${events.length} event${events.length !== 1 ? 's' : ''}`;
      }

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

  function initAnalytics() {
    document.getElementById('btn-refresh-heatmap')?.addEventListener('click', () => {
      const img = document.getElementById('static-heatmap-img');
      if (img) img.src = `/analytics/heatmap?t=${Date.now()}`;
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAnalytics);
  } else {
    initAnalytics();
  }

  window.TrackerApp.Analytics = {
    initChart: initTrafficChart,
    updateChart: updateTrafficChart,
    loadAlerts: loadAlertsTable,
  };
})();

