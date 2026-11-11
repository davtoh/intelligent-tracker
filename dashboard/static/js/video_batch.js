/**
 * Intelligent Tracker - Video Batch Analytics Submodule.
 * Handles Edge AI detection and Re-ID indexing execution on recorded video files.
 */

(function () {
  'use strict';

  let currentBatchFilename = null;
  const reportsByFilename = new Map();

  function getBaseRecordingName(filename) {
    return filename ? String(filename).trim().replace(/_h264(\.[^.]+)$/i, '$1') : '';
  }

  function invalidateCachedReports(filename) {
    if (!filename) return;
    const safeName = String(filename).trim();
    const baseName = getBaseRecordingName(safeName);
    const stem = baseName.replace(/\.[^.]+$/, '');
    reportsByFilename.delete(safeName);
    if (baseName) reportsByFilename.delete(baseName);
    for (const key of Array.from(reportsByFilename.keys())) {
      if (getBaseRecordingName(key).replace(/\.[^.]+$/, '') === stem) {
        reportsByFilename.delete(key);
      }
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
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

  function openBatchModal(filename) {
    if (!filename) return;
    currentBatchFilename = filename;

    const modal = document.getElementById('modal-video-batch-analyze');
    if (!modal) return;

    const sub = document.getElementById('batch-modal-filename-sub');
    if (sub) {
      const fullText = `Target: ${filename}`;
      if (window.TextTruncationManager) {
        window.TextTruncationManager.apply(sub, {
          fullText: fullText,
          mode: 'middle',
          maxLength: 38,
          preserveExt: true,
          label: 'Target Video File'
        });
      } else {
        sub.textContent = fullText;
        sub.title = fullText;
      }
    }

    // Populate detectors from capabilities if available
    const detSelect = document.getElementById('batch-detector-select');
    if (detSelect && window.CameraAIConfig) {
      // Keep YOLOv8 as default selection
      if (!detSelect.value) detSelect.value = 'yolov8';
    }

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

  function renderReportCards(rep, filename, meta = {}, runs = [], activeRunId = null) {
    const detector = meta.detector || 'yolov8';
    const stride = meta.sampleRate || meta.sample_rate || 1;
    const conf = meta.confidence !== undefined ? meta.confidence : 0.40;
    const classes = meta.classes && meta.classes.length ? meta.classes.join(', ') : 'All Classes';

    let historyDropdownHtml = '';
    if (runs && runs.length > 0) {
      const totalRuns = runs.length;
      const optionsHtml = runs.map((r, idx) => {
        const runNum = totalRuns - idx;
        const rCfg = r.config || {};
        const rDet = rCfg.detector || 'yolov8';
        const rConf = rCfg.confidence !== undefined ? Number(rCfg.confidence).toFixed(2) : '0.40';
        const rStride = rCfg.sample_rate || rCfg.sampleRate || 1;
        const isLatest = idx === 0;
        const tag = isLatest ? ' (Latest)' : (r.generated_at ? ` (${r.generated_at})` : '');
        const label = `Run #${runNum} [${rDet} conf=${rConf}${rStride > 1 ? ` s=${rStride}` : ''}]${tag}`;
        const isSelected = activeRunId ? r.run_id === activeRunId : isLatest;
        return `<option value="${escapeHtml(r.run_id)}" ${isSelected ? 'selected' : ''}>${escapeHtml(label)}</option>`;
      }).join('');

      historyDropdownHtml = `
        <div class="batch-history-switcher" style="display: flex; align-items: center; gap: 8px;">
          <label for="batch-report-run-select" style="font-size: 11px; color: #94a3b8; font-weight: 500;">History:</label>
          <select id="batch-report-run-select" class="form-select" style="font-size: 11px; padding: 2px 8px; border-radius: 4px; background: rgba(30, 41, 59, 0.9); border: 1px solid rgba(255, 255, 255, 0.2); color: #e2e8f0; cursor: pointer; max-width: 280px;">
            ${optionsHtml}
          </select>
        </div>
      `;
    }

    return `
      <div class="batch-report-card glass-panel">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px;">
          <h4 style="margin: 0;">📊 Occurrence Indexing Report (${escapeHtml(filename)})</h4>
          ${historyDropdownHtml}
        </div>
        <div class="batch-report-meta">
          <span class="batch-meta-pill accent">🧠 Model: ${escapeHtml(detector)}</span>
          <span class="batch-meta-pill cyan">⏱️ Stride: 1:${stride}</span>
          <span class="batch-meta-pill">🎯 Conf ≥ ${Number(conf).toFixed(2)}</span>
          <span class="batch-meta-pill green">🏷️ ${escapeHtml(classes)}</span>
        </div>
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

  function bindHistoryDropdown(container, filename, runs) {
    if (!container || !Array.isArray(runs) || runs.length === 0) return;
    const select = container.querySelector('#batch-report-run-select');
    if (!select) return;

    select.addEventListener('change', (e) => {
      const selectedRunId = e.target.value;
      const targetRun = runs.find(r => r.run_id === selectedRunId);
      if (!targetRun) return;

      const meta = {
        detector: targetRun.config?.detector || 'yolov8',
        sampleRate: targetRun.config?.sample_rate || targetRun.config?.sampleRate || 1,
        confidence: targetRun.config?.confidence !== undefined ? targetRun.config.confidence : 0.40,
        classes: targetRun.config?.classes || null,
      };

      container.innerHTML = renderReportCards(
        targetRun.report || targetRun.metrics || {},
        filename,
        meta,
        runs,
        selectedRunId
      );
      bindHistoryDropdown(container, filename, runs);
      if (window.OverlayLayers) {
        window.OverlayLayers.activateRun(filename, selectedRunId);
      } else {
        window.ScrubberOverlay?.loadDetections(filename, selectedRunId);
      }
    });
  }

  function syncContainerVisibility(filename) {
    const container = document.getElementById('video-batch-report-container');
    if (!container) return;
    const target = filename || currentBatchFilename;
    const activeJob = window.VideoJobClient?.getActiveJob(target);
    if (activeJob && activeJob.job_type === 'analytics') {
      container.style.display = 'none';
    } else {
      container.style.display = 'block';
    }
  }

  async function runBatchAnalytics(filename, options = {}) {
    if (!filename) return;
    const btn = document.getElementById('btn-video-analyze');
    const container = document.getElementById('video-batch-report-container');
    if (!container) return;

    const detector = options.detector || 'yolov8';
    const sampleRate = options.sampleRate || 1;
    const confidence = options.confidence !== undefined ? options.confidence : 0.40;
    const classes = options.classes || null;

    currentBatchFilename = filename;

    if (btn) {
      btn.disabled = true;
      btn.textContent = '⏳ Processing Analytics...';
    }

    try {
      if (window.VideoJobClient) {
        const payload = {
          sample_rate: sampleRate,
          detector: detector,
          confidence: confidence,
          classes: classes,
        };
        await window.VideoJobClient.startAnalytics(filename, payload);
      } else {
        container.innerHTML = `<div class="empty-state">Running Edge AI detector (${escapeHtml(detector)}) and Re-ID indexer on recording...</div>`;
        const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sample_rate: sampleRate,
            detector: detector,
            confidence: confidence,
            classes: classes,
          }),
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

  function bindEvents() {
    const modal = document.getElementById('modal-video-batch-analyze');
    const closeBtn = document.getElementById('modal-batch-close');
    const cancelBtn = document.getElementById('modal-batch-cancel');
    const form = document.getElementById('video-batch-analyze-form');
    const confRange = document.getElementById('batch-conf-range');
    const confInput = document.getElementById('batch-conf-input');

    if (closeBtn) closeBtn.addEventListener('click', closeBatchModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeBatchModal);

    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) closeBatchModal();
      });
    }

    if (confRange) {
      confRange.addEventListener('input', (e) => syncBatchConfidence(e.target.value));
    }
    if (confInput) {
      confInput.addEventListener('input', (e) => syncBatchConfidence(e.target.value));
      confInput.addEventListener('change', (e) => syncBatchConfidence(e.target.value));
    }

    // Preset tag buttons
    document.querySelectorAll('.btn-tag-preset[data-target="batch"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const classes = e.currentTarget.getAttribute('data-classes') || '';
        const classesInput = document.getElementById('batch-classes-input');
        if (classesInput) classesInput.value = classes;

        document.querySelectorAll('.btn-tag-preset[data-target="batch"]').forEach(b => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
      });
    });

    if (form) {
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        const detSelect = document.getElementById('batch-detector-select');
        const sampleSelect = document.getElementById('batch-sample-rate-select');
        const confInputEl = document.getElementById('batch-conf-input');
        const classesInputEl = document.getElementById('batch-classes-input');

        const detector = detSelect?.value || 'yolov8';
        const sampleRate = parseInt(sampleSelect?.value || '1', 10);
        const confVal = parseFloat(confInputEl?.value || '0.40');
        const confidence = isNaN(confVal) ? 0.40 : Math.min(Math.max(confVal, 0.05), 1.00);

        const classesRaw = (classesInputEl?.value || '').trim();
        const classes = classesRaw
          ? classesRaw.split(',').map(s => s.trim()).filter(Boolean)
          : null;

        closeBatchModal();
        runBatchAnalytics(currentBatchFilename, {
          detector: detector,
          sampleRate: sampleRate,
          confidence: confidence,
          classes: classes,
        });
      });
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal && modal.style.display === 'flex') {
        closeBatchModal();
      }
    });

    window.addEventListener('video-job-event', async (e) => {
      const { type, data } = e.detail || {};
      if (!data) return;
      const job = data;
      if (job.job_type !== 'analytics') return;
      if (type === 'job-finished') {
        invalidateCachedReports(job.filename);
      }
      if (job.filename !== currentBatchFilename) return;

      const btn = document.getElementById('btn-video-analyze');
      const container = document.getElementById('video-batch-report-container');

      if (type === 'job-started' || type === 'job-update') {
        if (job.status === 'running' || job.status === 'pending') {
          if (btn && currentBatchFilename === job.filename) {
            btn.disabled = false;
            btn.textContent = '⏳ Processing Analytics...';
          }
          if (container && currentBatchFilename === job.filename) {
            container.style.display = 'none';
          }
        }
      } else if (type === 'job-finished') {
        if (currentBatchFilename === job.filename) {
          if (btn) {
            btn.disabled = false;
            btn.textContent = '⚡ Run Batch Analytics';
          }
          if (container) {
            container.style.display = 'block';
            if (job.status === 'completed') {
              const baseRecordingName = getBaseRecordingName(job.filename);
              reportsByFilename.delete(job.filename);
              reportsByFilename.delete(baseRecordingName);
              const completedRunId = job.result?.run_id || null;
              await restoreReportForFile(job.filename, { activateRunId: completedRunId });
              if (!window.OverlayLayers) {
                window.ScrubberOverlay?.loadDetections(job.filename, completedRunId);
              }
            } else if (job.status === 'cancelled') {
              container.innerHTML = `<div class="empty-state" style="color:#f59e0b;">Analytics job for '${escapeHtml(job.filename)}' was cancelled.</div>`;
            } else if (job.status === 'failed' && window.VideoJobClient) {
              window.VideoJobClient.renderErrorAlert(container, job.error, () => runBatchAnalytics(job.filename));
            }
          }
        }
      }
    });
  }

  function setCurrentBatchFilename(filename) {
    currentBatchFilename = filename ? String(filename).trim() : null;
    syncContainerVisibility(currentBatchFilename);
  }

  function renderLatestRun(container, filename, runs, options = {}) {
    const latest = runs[0];
    const meta = {
      detector: latest.config?.detector || 'yolov8',
      sampleRate: latest.config?.sample_rate || latest.config?.sampleRate || 1,
      confidence: latest.config?.confidence !== undefined ? latest.config.confidence : 0.40,
      classes: latest.config?.classes || null,
    };
    container.innerHTML = renderReportCards(
      latest.report || latest.metrics || {},
      filename,
      meta,
      runs,
      latest.run_id
    );
    bindHistoryDropdown(container, filename, runs);
    container.style.display = 'block';
    window.OverlayLayers?.syncRuns(filename, runs, options);
  }

  async function restoreReportForFile(filename, options = {}) {
    if (!filename) return;
    currentBatchFilename = filename;
    const container = document.getElementById('video-batch-report-container');
    if (!container) return;

    syncContainerVisibility(filename);

    const activeJob = window.VideoJobClient?.getActiveJob(filename);
    if (activeJob && activeJob.job_type === 'analytics') {
      container.style.display = 'none';
      return;
    }

    if (reportsByFilename.has(filename)) {
      const cachedRuns = reportsByFilename.get(filename);
      if (Array.isArray(cachedRuns) && cachedRuns.length > 0) {
        renderLatestRun(container, filename, cachedRuns, options);
        return;
      }
    }

    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/reports`);
      if (resp.ok) {
        const runs = await resp.json();
        if (currentBatchFilename !== filename) return;

        if (Array.isArray(runs) && runs.length > 0) {
          reportsByFilename.set(filename, runs);
          renderLatestRun(container, filename, runs, options);
          return;
        }
      }
    } catch (e) {
      console.debug('Failed to restore stacked reports for', filename, e);
    }

    if (currentBatchFilename === filename) {
      container.innerHTML = '<div class="empty-state">Click <strong>⚡ Batch Video Analytics</strong> to catalog entity sightings and dwell times.</div>';
      container.style.display = 'block';
      window.OverlayLayers?.syncRuns(filename, []);
    }
  }

  function init() {
    bindEvents();
  }

  window.VideoBatch = {
    init: init,
    runBatchAnalytics: runBatchAnalytics,
    renderReportCards: renderReportCards,
    openBatchModal: openBatchModal,
    closeBatchModal: closeBatchModal,
    setCurrentBatchFilename: setCurrentBatchFilename,
    restoreReportForFile: restoreReportForFile,
    syncContainerVisibility: syncContainerVisibility,
    invalidateCachedReports: invalidateCachedReports,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
