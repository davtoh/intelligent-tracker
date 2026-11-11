/**
 * Intelligent Tracker - Video Batch Report Rendering & Lifecycle Module.
 * Manages report cards, run history switching, per-run deletion,
 * clear-all deletion, and OverlayLayers / ScrubberOverlay synchronization.
 */

(function () {
  'use strict';

  const OVERLAY_STORAGE_KEY = 'intelligent_tracker_overlay_layers_v1';
  const reportsByFilename = new Map();
  let currentReportFilename = null;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function getBaseRecordingName(filename) {
    return filename ? String(filename).trim().replace(/_h264(\.[^.]+)$/i, '$1') : '';
  }

  function getBaseStem(filename) {
    return getBaseRecordingName(filename).replace(/\.[^.]+$/, '');
  }

  function notifyToast(message, type = 'info') {
    if (typeof window.showToast === 'function') {
      window.showToast(message, type);
    }
  }

  function setCurrentFilename(filename) {
    currentReportFilename = filename ? String(filename).trim() : null;
  }

  function getCurrentFilename() {
    return currentReportFilename;
  }

  function invalidateCachedReports(filename) {
    if (!filename) return;
    const safeName = String(filename).trim();
    const baseName = getBaseRecordingName(safeName);
    const stem = getBaseStem(safeName);
    reportsByFilename.delete(safeName);
    if (baseName) reportsByFilename.delete(baseName);
    for (const key of Array.from(reportsByFilename.keys())) {
      if (getBaseStem(key) === stem) {
        reportsByFilename.delete(key);
      }
    }
  }

  function clearStoredOverlaySelection(filename) {
    const stem = getBaseStem(filename);
    if (!stem) return;
    try {
      const raw = localStorage.getItem(OVERLAY_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        delete parsed[stem];
        localStorage.setItem(OVERLAY_STORAGE_KEY, JSON.stringify(parsed));
      }
    } catch (_err) {
      // Ignore storage quota or private-mode restrictions
    }
  }

  function buildMetaFromRun(run) {
    const cfg = run?.config || {};
    return {
      detector: cfg.detector || 'yolov8',
      sampleRate: cfg.sample_rate || cfg.sampleRate || 1,
      confidence: cfg.confidence !== undefined ? cfg.confidence : 0.40,
      classes: cfg.classes || null,
    };
  }

  function buildHistorySwitcherHtml(filename, runs, activeRunId) {
    if (!Array.isArray(runs) || runs.length === 0) return '';
    const totalRuns = runs.length;
    const selectedId = activeRunId && runs.some(r => r.run_id === activeRunId)
      ? activeRunId
      : runs[0].run_id;

    const optionsHtml = runs.map((r, idx) => {
      const runNum = totalRuns - idx;
      const rCfg = r.config || {};
      const rDet = rCfg.detector || 'yolov8';
      const rConf = rCfg.confidence !== undefined ? Number(rCfg.confidence).toFixed(2) : '0.40';
      const rStride = rCfg.sample_rate || rCfg.sampleRate || 1;
      const tag = idx === 0 ? ' (Latest)' : (r.generated_at ? ` (${r.generated_at})` : '');
      const label = `Run #${runNum} [${rDet} conf=${rConf}${rStride > 1 ? ` s=${rStride}` : ''}]${tag}`;
      const isSelected = r.run_id === selectedId;
      return `<option value="${escapeHtml(r.run_id)}" ${isSelected ? 'selected' : ''}>${escapeHtml(label)}</option>`;
    }).join('');

    return `
      <div class="batch-history-switcher">
        <label for="batch-report-run-select" class="batch-history-label">History:</label>
        <select id="batch-report-run-select" class="form-select batch-history-select">
          ${optionsHtml}
        </select>
        <div class="batch-report-actions">
          <button type="button" id="btn-delete-report-run" class="btn btn-xs btn-outline btn-danger-outline" data-filename="${escapeHtml(filename)}" data-run-id="${escapeHtml(selectedId)}" title="Delete selected report run">🗑️ Delete Run</button>
          <button type="button" id="btn-clear-report-runs" class="btn btn-xs btn-outline btn-danger-outline" data-filename="${escapeHtml(filename)}" title="Clear all report runs for this recording">🧹 Clear All</button>
        </div>
      </div>
    `;
  }

  function renderReportCards(rep, filename, meta = {}, runs = [], activeRunId = null) {
    const detector = meta.detector || 'yolov8';
    const stride = meta.sampleRate || meta.sample_rate || 1;
    const conf = meta.confidence !== undefined ? meta.confidence : 0.40;
    const classes = meta.classes && meta.classes.length ? meta.classes.join(', ') : 'All Classes';
    const historyHtml = buildHistorySwitcherHtml(filename, runs, activeRunId);

    return `
      <div class="batch-report-card glass-panel">
        <div class="batch-report-header">
          <h4 class="batch-report-title" title="Occurrence Indexing Report (${escapeHtml(filename)})">📊 Occurrence Indexing Report (${escapeHtml(filename)})</h4>
          ${historyHtml}
        </div>
        <div class="batch-report-meta">
          <span class="batch-meta-pill accent">🧠 Model: ${escapeHtml(detector)}</span>
          <span class="batch-meta-pill cyan">⏱️ Stride: 1:${stride}</span>
          <span class="batch-meta-pill">🎯 Conf ≥ ${Number(conf).toFixed(2)}</span>
          <span class="batch-meta-pill green">🏷️ ${escapeHtml(classes)}</span>
        </div>
        <div class="kpi-row batch-report-kpi-row">
          <div class="kpi-card glass-panel"><div class="kpi-label">Frames Processed</div><div class="kpi-value cyan">${rep.frames_processed || 0}</div></div>
          <div class="kpi-card glass-panel"><div class="kpi-label">Detections</div><div class="kpi-value green">${rep.total_detections || 0}</div></div>
          <div class="kpi-card glass-panel"><div class="kpi-label">Sightings Recorded</div><div class="kpi-value cyan">${rep.total_sightings || 0}</div></div>
          <div class="kpi-card glass-panel"><div class="kpi-label">Unique Entities</div><div class="kpi-value green">${rep.unique_entities_identified || 0}</div></div>
        </div>
        <div class="batch-report-footer">
          Audit records cataloged in <code>TrackerDB</code>. View complete results in <strong>Sighting Timeline</strong> tab.
        </div>
      </div>
    `;
  }

  function setActionButtonsDisabled(container, disabled) {
    if (!container) return;
    ['#btn-delete-report-run', '#btn-clear-report-runs'].forEach((sel) => {
      const btn = container.querySelector(sel);
      if (btn) btn.disabled = Boolean(disabled);
    });
  }

  function renderEmptyState(container) {
    if (!container) return;
    container.innerHTML = '<div class="empty-state">Click <strong>⚡ Batch Video Analytics</strong> to catalog entity sightings and dwell times.</div>';
    container.style.display = 'block';
    window.OverlayLayers?.syncRuns?.(currentReportFilename, []);
    window.ScrubberOverlay?.clearLayers?.({ keepLive: true });
  }

  function bindReportControls(container, filename, runs, activeRunId) {
    if (!container || !Array.isArray(runs) || runs.length === 0) return;

    const select = container.querySelector('#batch-report-run-select');
    if (select) {
      select.addEventListener('change', (e) => {
        const selectedRunId = e.target.value;
        const targetRun = runs.find(r => r.run_id === selectedRunId);
        if (!targetRun) return;
        container.innerHTML = renderReportCards(
          targetRun.report || targetRun.metrics || {},
          filename,
          buildMetaFromRun(targetRun),
          runs,
          selectedRunId
        );
        bindReportControls(container, filename, runs, selectedRunId);
        if (window.OverlayLayers) {
          window.OverlayLayers.activateRun(filename, selectedRunId);
        } else {
          window.ScrubberOverlay?.loadDetections?.(filename, selectedRunId);
        }
      });
    }

    const delBtn = container.querySelector('#btn-delete-report-run');
    if (delBtn) {
      delBtn.addEventListener('click', () => {
        const rid = delBtn.getAttribute('data-run-id') || activeRunId || select?.value;
        if (rid) deleteReportRun(filename, rid);
      });
    }

    const clearBtn = container.querySelector('#btn-clear-report-runs');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => clearAllReportRuns(filename));
    }
  }

  function renderLatestRun(container, filename, runs, options = {}) {
    if (!container || !Array.isArray(runs) || runs.length === 0) return;
    const latest = runs[0];
    container.innerHTML = renderReportCards(
      latest.report || latest.metrics || {},
      filename,
      buildMetaFromRun(latest),
      runs,
      latest.run_id
    );
    bindReportControls(container, filename, runs, latest.run_id);
    container.style.display = 'block';
    window.OverlayLayers?.syncRuns?.(filename, runs, options);
  }

  async function fetchFreshRuns(filename) {
    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/reports`);
      if (!resp.ok) return [];
      const runs = await resp.json();
      return Array.isArray(runs) ? runs : [];
    } catch (_err) {
      return [];
    }
  }

  async function deleteReportRun(filename, runId) {
    if (!filename || !runId) return false;
    const container = document.getElementById('video-batch-report-container');
    setActionButtonsDisabled(container, true);
    try {
      const resp = await fetch(
        `/api/videos/${encodeURIComponent(filename)}/reports/${encodeURIComponent(runId)}`,
        { method: 'DELETE' }
      );
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        notifyToast(`Failed to delete run '${runId}': ${err.detail || resp.statusText}`, 'error');
        setActionButtonsDisabled(container, false);
        return false;
      }

      invalidateCachedReports(filename);
      window.ScrubberOverlay?.removeLayer?.(runId);

      const remainingRuns = await fetchFreshRuns(filename);
      if (currentReportFilename && currentReportFilename !== filename) return true;

      if (remainingRuns.length > 0) {
        reportsByFilename.set(filename, remainingRuns);
        if (container) renderLatestRun(container, filename, remainingRuns);
      } else {
        clearStoredOverlaySelection(filename);
        renderEmptyState(container);
      }
      notifyToast(`Deleted report run '${runId}'.`, 'success');
      return true;
    } catch (e) {
      notifyToast(`Error deleting report run: ${e.message}`, 'error');
      setActionButtonsDisabled(container, false);
      return false;
    }
  }

  async function clearAllReportRuns(filename) {
    if (!filename) return false;
    const container = document.getElementById('video-batch-report-container');
    setActionButtonsDisabled(container, true);
    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/reports`, {
        method: 'DELETE',
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        notifyToast(`Failed to clear report runs: ${err.detail || resp.statusText}`, 'error');
        setActionButtonsDisabled(container, false);
        return false;
      }

      const payload = await resp.json().catch(() => ({}));
      invalidateCachedReports(filename);
      clearStoredOverlaySelection(filename);
      window.ScrubberOverlay?.clearLayers?.({ keepLive: true });
      window.OverlayLayers?.syncRuns?.(filename, []);

      if (!currentReportFilename || currentReportFilename === filename) {
        renderEmptyState(container);
      }
      notifyToast(`Cleared ${payload.cleared_count ?? 0} report run(s) for '${filename}'.`, 'success');
      return true;
    } catch (e) {
      notifyToast(`Error clearing report runs: ${e.message}`, 'error');
      setActionButtonsDisabled(container, false);
      return false;
    }
  }

  async function restoreReportForFile(filename, options = {}) {
    if (!filename) return;
    currentReportFilename = filename;
    const container = document.getElementById('video-batch-report-container');
    if (!container) return;

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
        if (currentReportFilename !== filename) return;
        if (Array.isArray(runs) && runs.length > 0) {
          reportsByFilename.set(filename, runs);
          renderLatestRun(container, filename, runs, options);
          return;
        }
      }
    } catch (e) {
      console.debug('Failed to restore stacked reports for', filename, e);
    }

    if (currentReportFilename === filename) {
      renderEmptyState(container);
    }
  }

  window.VideoBatchReports = {
    setCurrentFilename,
    getCurrentFilename,
    invalidateCachedReports,
    renderReportCards,
    renderLatestRun,
    renderEmptyState,
    restoreReportForFile,
    deleteReportRun,
    clearAllReportRuns,
  };
})();

