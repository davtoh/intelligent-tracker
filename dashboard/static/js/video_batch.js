/**
 * Intelligent Tracker - Video Batch Analytics Submodule.
 * Handles Edge AI detection and Re-ID indexing execution on recorded video files.
 */

(function () {
  'use strict';

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderReportCards(rep, filename) {
    return `
      <div class="batch-report-card glass-panel">
        <h4>📊 Occurrence Indexing Report (${escapeHtml(filename)})</h4>
        <div class="kpi-row" style="margin-top: 10px;">
          <div class="kpi-card glass-panel">
            <div class="kpi-label">Frames Processed</div>
            <div class="kpi-value cyan">${rep.frames_processed || 0}</div>
          </div>
          <div class="kpi-card glass-panel">
            <div class="kpi-label">Detections</div>
            <div class="kpi-value green">${rep.total_detections || 0}</div>
          </div>
          <div class="kpi-card glass-panel">
            <div class="kpi-label">Sightings Recorded</div>
            <div class="kpi-value cyan">${rep.total_sightings || 0}</div>
          </div>
          <div class="kpi-card glass-panel">
            <div class="kpi-label">Unique Entities</div>
            <div class="kpi-value green">${rep.unique_entities_identified || 0}</div>
          </div>
        </div>
        <div style="margin-top: 12px; font-size: 13px; color: #94a3b8;">
          Audit records cataloged in <code>TrackerDB</code>. View complete results in <strong>Sighting Timeline</strong> tab.
        </div>
      </div>
    `;
  }

  async function runBatchAnalytics(filename) {
    if (!filename) return;
    const btn = document.getElementById('btn-video-analyze');
    const container = document.getElementById('video-batch-report-container');
    if (!container) return;

    if (btn) {
      btn.disabled = true;
      btn.textContent = '⏳ Processing Analytics...';
    }
    container.innerHTML = '<div class="empty-state">Running Edge AI detector and Re-ID indexer on recording...</div>';

    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/analyze?sample_rate=1`, {
        method: 'POST'
      });
      const data = await resp.json();

      if (data.status === 'success') {
        container.innerHTML = renderReportCards(data.report || {}, filename);
      } else {
        container.innerHTML = `<div class="empty-state" style="color:#ef4444;">Analysis failed: ${escapeHtml(data.detail || 'Error')}</div>`;
      }
    } catch (e) {
      container.innerHTML = `<div class="empty-state" style="color:#ef4444;">Request error: ${escapeHtml(e.message)}</div>`;
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = '⚡ Run Batch Occurrence Report';
      }
    }
  }

  window.VideoBatch = {
    runBatchAnalytics: runBatchAnalytics,
    renderReportCards: renderReportCards,
  };
})();

