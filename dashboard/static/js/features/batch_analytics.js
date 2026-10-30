/**
 * Intelligent Tracker - Offline Batch Video Occurrence Analysis & Transcoder.
 * Invokes server-side batch inference, progress indexing, and report rendering.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  const escapeHtml = window.escapeHtml || (s => s);

  async function runBatchAnalytics(filename, btnAnalyzeVideo, batchReportContainer) {
    if (!filename || !batchReportContainer) return;
    if (btnAnalyzeVideo) {
      btnAnalyzeVideo.disabled = true;
      btnAnalyzeVideo.textContent = '⏳ Processing Analytics...';
    }
    batchReportContainer.innerHTML = '<div class="empty-state">Running Edge AI detector and Re-ID indexer on recording...</div>';

    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/analyze?sample_rate=1`, {
        method: 'POST'
      });
      const data = await resp.json();

      if (data.status === 'success') {
        const rep = data.report || {};
        batchReportContainer.innerHTML = `
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
      } else {
        batchReportContainer.innerHTML = `<div class="empty-state" style="color:#ef4444;">Analysis failed: ${escapeHtml(data.detail || 'Error')}</div>`;
      }
    } catch (e) {
      batchReportContainer.innerHTML = `<div class="empty-state" style="color:#ef4444;">Request error: ${escapeHtml(e.message)}</div>`;
    } finally {
      if (btnAnalyzeVideo) {
        btnAnalyzeVideo.disabled = false;
        btnAnalyzeVideo.textContent = '⚡ Run Batch Occurrence Report';
      }
    }
  }

  window.TrackerApp.BatchAnalytics = {
    run: runBatchAnalytics,
  };
})();

