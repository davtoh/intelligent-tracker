/**
 * Intelligent Tracker - Video Batch Analytics Submodule.
 * Handles Edge AI detection modal, job execution, and delegates
 * report view rendering and deletion lifecycle to VideoBatchReports.
 */

(function () {
  'use strict';

  let currentBatchFilename = null;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function invalidateCachedReports(filename) {
    window.VideoBatchReports?.invalidateCachedReports?.(filename);
  }

  function renderReportCards(rep, filename, meta = {}, runs = [], activeRunId = null) {
    if (!window.VideoBatchReports) return '';
    return window.VideoBatchReports.renderReportCards(rep, filename, meta, runs, activeRunId);
  }

  function syncBatchConfidence(val) {
    const num = Math.min(Math.max(parseFloat(val) || 0.40, 0.05), 1.00);
    const formatted = num.toFixed(2);
    const range = document.getElementById('batch-conf-range');
    const input = document.getElementById('batch-conf-input');
    const display = document.getElementById('batch-conf-display');
    if (range && range.value !== formatted) range.value = formatted;
    if (input && input.value !== formatted) input.value = formatted;
    if (display) display.textContent = formatted;
  }

  function applyModalTargetTitle(filename) {
    const sub = document.getElementById('batch-modal-filename-sub');
    if (!sub) return;
    const fullText = `Target: ${filename}`;
    if (window.TextTruncationManager) {
      window.TextTruncationManager.apply(sub, {
        fullText,
        mode: 'middle',
        maxLength: 38,
        preserveExt: true,
        label: 'Target Video File',
      });
    } else {
      sub.textContent = fullText;
      sub.title = fullText;
    }
  }

  function openBatchModal(filename) {
    if (!filename) return;
    setCurrentBatchFilename(filename);

    const modal = document.getElementById('modal-video-batch-analyze');
    if (!modal) return;
    applyModalTargetTitle(filename);

    const detSelect = document.getElementById('batch-detector-select');
    if (detSelect && window.CameraAIConfig && !detSelect.value) detSelect.value = 'yolov8';

    const sampleSelect = document.getElementById('batch-sample-rate-select');
    if (sampleSelect) sampleSelect.value = '1';

    syncBatchConfidence(0.40);
    const classesInput = document.getElementById('batch-classes-input');
    if (classesInput) classesInput.value = '';

    document.querySelectorAll('.btn-tag-preset[data-target="batch"]').forEach(btn => {
      btn.classList.remove('active');
    });
    modal.style.display = 'flex';
  }

  function closeBatchModal() {
    const modal = document.getElementById('modal-video-batch-analyze');
    if (modal) modal.style.display = 'none';
  }

  function syncContainerVisibility(filename) {
    const container = document.getElementById('video-batch-report-container');
    if (!container) return;
    const target = filename || currentBatchFilename;
    const activeJob = window.VideoJobClient?.getActiveJob(target);
    container.style.display = activeJob && activeJob.job_type === 'analytics' ? 'none' : 'block';
  }

  function setCurrentBatchFilename(filename) {
    currentBatchFilename = filename ? String(filename).trim() : null;
    window.VideoBatchReports?.setCurrentFilename?.(currentBatchFilename);
    syncContainerVisibility(currentBatchFilename);
  }

  async function restoreReportForFile(filename, options = {}) {
    if (!filename) return;
    setCurrentBatchFilename(filename);
    const container = document.getElementById('video-batch-report-container');
    if (!container) return;

    const activeJob = window.VideoJobClient?.getActiveJob(filename);
    if (activeJob && activeJob.job_type === 'analytics') {
      container.style.display = 'none';
      return;
    }
    if (window.VideoBatchReports) {
      await window.VideoBatchReports.restoreReportForFile(filename, options);
    }
  }

  async function runDirectAnalyticsFetch(filename, container, btn, payload) {
    container.innerHTML = `<div class="empty-state">Running Edge AI detector (${escapeHtml(payload.detector)}) and Re-ID indexer on recording...</div>`;
    const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (data.status === 'success') {
      invalidateCachedReports(filename);
      const completedRunId = data.report?.run_id || null;
      await restoreReportForFile(filename, { activateRunId: completedRunId });
      if (!window.OverlayLayers && completedRunId) {
        window.ScrubberOverlay?.loadDetections(filename, completedRunId);
      }
    } else {
      container.innerHTML = `<div class="empty-state" style="color:#ef4444;">Analysis failed: ${escapeHtml(data.detail || 'Error')}</div>`;
    }
    if (btn) {
      btn.disabled = false;
      btn.textContent = '⚡ Run Batch Analytics';
    }
  }

  async function runBatchAnalytics(filename, options = {}) {
    if (!filename) return;
    const btn = document.getElementById('btn-video-analyze');
    const container = document.getElementById('video-batch-report-container');
    if (!container) return;

    const payload = {
      sample_rate: options.sampleRate || 1,
      detector: options.detector || 'yolov8',
      confidence: options.confidence !== undefined ? options.confidence : 0.40,
      classes: options.classes || null,
    };
    setCurrentBatchFilename(filename);

    if (btn) {
      btn.disabled = true;
      btn.textContent = '⏳ Processing Analytics...';
    }

    try {
      if (window.VideoJobClient) {
        await window.VideoJobClient.startAnalytics(filename, payload);
      } else {
        await runDirectAnalyticsFetch(filename, container, btn, payload);
      }
    } catch (e) {
      if (window.VideoJobClient) {
        window.VideoJobClient.renderErrorAlert(container, e.message, () => runBatchAnalytics(filename, options));
      } else {
        container.innerHTML = `<div class="empty-state" style="color:#ef4444;">Request error: ${escapeHtml(e.message)}</div>`;
      }
      if (btn) {
        btn.disabled = false;
        btn.textContent = '⚡ Run Batch Analytics';
      }
    }
  }

  function handleBatchFormSubmit(e) {
    e.preventDefault();
    const detSelect = document.getElementById('batch-detector-select');
    const sampleSelect = document.getElementById('batch-sample-rate-select');
    const confInputEl = document.getElementById('batch-conf-input');
    const classesInputEl = document.getElementById('batch-classes-input');

    const confVal = parseFloat(confInputEl?.value || '0.40');
    const classesRaw = (classesInputEl?.value || '').trim();
    const classes = classesRaw ? classesRaw.split(',').map(s => s.trim()).filter(Boolean) : null;

    closeBatchModal();
    runBatchAnalytics(currentBatchFilename, {
      detector: detSelect?.value || 'yolov8',
      sampleRate: parseInt(sampleSelect?.value || '1', 10),
      confidence: isNaN(confVal) ? 0.40 : Math.min(Math.max(confVal, 0.05), 1.00),
      classes,
    });
  }

  async function handleVideoJobEvent(e) {
    const { type, data: job } = e.detail || {};
    if (!job || job.job_type !== 'analytics') return;
    if (type === 'job-finished') invalidateCachedReports(job.filename);
    if (job.filename !== currentBatchFilename) return;

    const btn = document.getElementById('btn-video-analyze');
    const container = document.getElementById('video-batch-report-container');

    if ((type === 'job-started' || type === 'job-update') && (job.status === 'running' || job.status === 'pending')) {
      if (btn) { btn.disabled = false; btn.textContent = '⏳ Processing Analytics...'; }
      if (container) container.style.display = 'none';
      return;
    }

    if (type !== 'job-finished') return;
    if (btn) { btn.disabled = false; btn.textContent = '⚡ Run Batch Analytics'; }
    if (!container) return;
    container.style.display = 'block';

    if (job.status === 'completed') {
      const completedRunId = job.result?.run_id || null;
      await restoreReportForFile(job.filename, { activateRunId: completedRunId });
      if (!window.OverlayLayers) window.ScrubberOverlay?.loadDetections(job.filename, completedRunId);
    } else if (job.status === 'cancelled') {
      container.innerHTML = `<div class="empty-state" style="color:#f59e0b;">Analytics job for '${escapeHtml(job.filename)}' was cancelled.</div>`;
    } else if (job.status === 'failed' && window.VideoJobClient) {
      window.VideoJobClient.renderErrorAlert(container, job.error, () => runBatchAnalytics(job.filename));
    }
  }

  function bindEvents() {
    const modal = document.getElementById('modal-video-batch-analyze');
    document.getElementById('modal-batch-close')?.addEventListener('click', closeBatchModal);
    document.getElementById('modal-batch-cancel')?.addEventListener('click', closeBatchModal);
    modal?.addEventListener('click', (e) => { if (e.target === modal) closeBatchModal(); });

    document.getElementById('batch-conf-range')?.addEventListener('input', (e) => syncBatchConfidence(e.target.value));
    const confInput = document.getElementById('batch-conf-input');
    confInput?.addEventListener('input', (e) => syncBatchConfidence(e.target.value));
    confInput?.addEventListener('change', (e) => syncBatchConfidence(e.target.value));

    document.querySelectorAll('.btn-tag-preset[data-target="batch"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const classesInput = document.getElementById('batch-classes-input');
        if (classesInput) classesInput.value = e.currentTarget.getAttribute('data-classes') || '';
        document.querySelectorAll('.btn-tag-preset[data-target="batch"]').forEach(b => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
      });
    });

    document.getElementById('video-batch-analyze-form')?.addEventListener('submit', handleBatchFormSubmit);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal && modal.style.display === 'flex') closeBatchModal();
    });
    window.addEventListener('video-job-event', handleVideoJobEvent);
  }

  function init() {
    bindEvents();
  }

  window.VideoBatch = {
    init,
    runBatchAnalytics,
    renderReportCards,
    openBatchModal,
    closeBatchModal,
    setCurrentBatchFilename,
    restoreReportForFile,
    syncContainerVisibility,
    invalidateCachedReports,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
