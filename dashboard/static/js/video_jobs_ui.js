/**
 * Intelligent Tracker - Video Job UI & Progress Rendering Helpers.
 * Extracted from video_jobs.js to enforce < 350L modularity budget.
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

  function buildConflictModalHtml(activeJob, targetActionName) {
    const typeLabel = activeJob.job_type === 'transcode' ? 'Convert to H.264' : 'Batch Video Analytics';
    const pct = (activeJob.progress || 0).toFixed(1);
    return `
      <div class="modal-dialog glass-panel" style="max-width: 460px; width: 92%; margin: auto; padding: 20px; border-radius: 10px; background: rgba(17, 24, 39, 0.95); border: 1px solid rgba(255, 255, 255, 0.15); box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <h3 style="margin: 0; font-size: 1.15rem; color: #f59e0b; display: flex; align-items: center; gap: 8px;"><span>⚠️</span> Task in Progress</h3>
          <button id="btn-conflict-close" style="background: none; border: none; color: #9ca3af; font-size: 1.25rem; cursor: pointer; padding: 4px 8px; min-height: 32px; min-width: 32px;">✕</button>
        </div>
        <div style="font-size: 0.9rem; color: #e5e7eb; line-height: 1.5; margin-bottom: 16px;">
          <p style="margin: 0 0 10px 0;">A <strong>${escapeHtml(typeLabel)}</strong> job is currently running on <span style="color: #60a5fa; font-family: monospace;">${escapeHtml(activeJob.filename)}</span>.</p>
          <div style="background: rgba(0, 0, 0, 0.35); padding: 10px; border-radius: 6px; margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: #9ca3af; margin-bottom: 6px;"><span>Progress: ${pct}%</span><span>Stage: ${escapeHtml(activeJob.stage || 'running')}</span></div>
            <div style="width: 100%; height: 8px; background: rgba(255, 255, 255, 0.1); border-radius: 4px; overflow: hidden;"><div style="width: ${pct}%; height: 100%; background: #3b82f6; transition: width 0.3s ease;"></div></div>
          </div>
          <p style="margin: 0; color: #9ca3af; font-size: 0.85rem;">Cancel this job to start <strong>${escapeHtml(targetActionName)}</strong>, or keep the existing job running?</p>
        </div>
        <div style="display: flex; justify-content: flex-end; gap: 10px;">
          <button id="btn-conflict-keep" class="btn btn-secondary" style="min-height: 36px; padding: 6px 14px; border-radius: 6px; cursor: pointer;">Keep Running</button>
          <button id="btn-conflict-cancel-proceed" class="btn btn-danger" style="min-height: 36px; padding: 6px 14px; border-radius: 6px; cursor: pointer; background: #dc2626; color: white; border: none;">Cancel &amp; Proceed</button>
        </div>
      </div>`;
  }

  function closeConflictModal() {
    const modal = document.getElementById('modal-job-conflict');
    if (modal && modal.parentNode) modal.parentNode.removeChild(modal);
  }

  function showConflictModal(client, activeJob, targetActionName, onCancelAndProceed, onKeepRunning) {
    closeConflictModal();
    const modal = document.createElement('div');
    modal.id = 'modal-job-conflict';
    modal.className = 'modal-backdrop';
    Object.assign(modal.style, {
      position: 'fixed', inset: '0', zIndex: '9999', background: 'rgba(0, 0, 0, 0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    });
    modal.innerHTML = buildConflictModalHtml(activeJob, targetActionName);
    document.body.appendChild(modal);

    modal.querySelector('#btn-conflict-close')?.addEventListener('click', () => { closeConflictModal(); if (onKeepRunning) onKeepRunning(); });
    modal.querySelector('#btn-conflict-keep')?.addEventListener('click', () => { closeConflictModal(); if (onKeepRunning) onKeepRunning(); });
    modal.querySelector('#btn-conflict-cancel-proceed')?.addEventListener('click', async () => {
      const btn = modal.querySelector('#btn-conflict-cancel-proceed');
      if (btn) { btn.disabled = true; btn.textContent = 'Cancelling...'; }
      await client.cancelJob(activeJob.job_id);
      closeConflictModal();
      if (onCancelAndProceed) onCancelAndProceed();
    });
  }

  function formatJobSubtext(job) {
    const metrics = job.metrics || {};
    if (job.job_type === 'transcode') {
      return [metrics.fps ? `${metrics.fps} FPS` : '', metrics.elapsed ? `${metrics.elapsed}s` : ''].filter(Boolean).join(' • ');
    }
    const frames = metrics.total_frames ? `${metrics.read_frames || 0}/${metrics.total_frames} frames` : '';
    const sightings = metrics.sightings ? `${metrics.sightings} sightings` : '';
    const speed = metrics.fps ? `${metrics.fps} FPS` : '';
    return [frames, sightings, speed].filter(Boolean).join(' • ');
  }

  function renderProgressBar(client, container, job, onCancelClick) {
    if (!container || !job) return;
    const label = job.job_type === 'transcode' ? '⚡ Converting to H.264...' : '🧠 Indexing Batch Occurrences...';
    const pct = Math.min(100, Math.max(0, job.progress || 0)).toFixed(1);
    const subtext = formatJobSubtext(job);

    container.innerHTML = `
      <div class="video-job-progress-panel glass-panel" style="padding: 10px 14px; margin-bottom: 12px; border-radius: 8px; background: rgba(59, 130, 246, 0.12); border: 1px solid rgba(59, 130, 246, 0.4);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
          <span style="color: #60a5fa; font-weight: 600; font-size: 0.85rem;">${escapeHtml(label)}</span>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-weight: 700; font-size: 0.85rem; color: #e5e7eb;">${pct}%</span>
            <button class="btn btn-xs btn-danger btn-cancel-active-job" style="min-height: 28px; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; cursor: pointer; background: #dc2626; color: white; border: none;">✖ Cancel</button>
          </div>
        </div>
        <div style="width: 100%; height: 8px; background: rgba(255, 255, 255, 0.1); border-radius: 4px; overflow: hidden;"><div style="width: ${pct}%; height: 100%; background: #3b82f6; border-radius: 4px; transition: width 0.3s ease;"></div></div>
        ${subtext ? `<div style="font-size: 0.75rem; color: #9ca3af; margin-top: 6px;">${escapeHtml(subtext)}</div>` : ''}
      </div>`;

    container.querySelector('.btn-cancel-active-job')?.addEventListener('click', () => {
      if (onCancelClick) onCancelClick(job);
      else client.cancelJob(job.job_id);
    });
  }

  function renderErrorAlert(container, errorText, onRetry) {
    if (!container) return;
    container.innerHTML = `
      <div class="video-job-error-alert glass-panel" style="padding: 10px 14px; margin-bottom: 12px; border-radius: 8px; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.4); display: flex; align-items: center; justify-content: space-between;">
        <div style="color: #ef4444; font-size: 0.85rem; flex: 1; padding-right: 10px;"><strong>⚠️ Task Failed:</strong> ${escapeHtml(errorText || 'Unknown error occurred')}</div>
        ${onRetry ? '<button class="btn btn-xs btn-secondary btn-retry-job" style="min-height: 28px; padding: 2px 10px; font-size: 0.75rem; cursor: pointer;">↻ Retry</button>' : ''}
      </div>`;
    if (onRetry) container.querySelector('.btn-retry-job')?.addEventListener('click', onRetry);
  }

  function syncDrawerJobsBadge(activeCount) {
    const drawerBadge = document.getElementById('drawer-jobs-badge');
    if (!drawerBadge) return;
    drawerBadge.textContent = String(activeCount || 0);
    drawerBadge.style.display = activeCount > 0 ? 'inline-block' : 'none';
  }

  function syncActiveJobUI(client, filename) {
    const banner = document.getElementById('scrubber-active-job-banner');
    const badge = document.getElementById('scrubber-header-job-badge');
    const btnAnalyze = document.getElementById('btn-video-analyze');
    syncDrawerJobsBadge(client.getAllActiveJobs().length);
    if (!filename) {
      if (banner) { banner.style.display = 'none'; banner.innerHTML = ''; }
      if (badge) { badge.style.display = 'none'; badge.textContent = ''; }
      return;
    }

    const activeJob = client.getActiveJob(filename);
    window.VideoBatch?.syncContainerVisibility?.(filename);
    if (activeJob) {
      if (banner) { renderProgressBar(client, banner, activeJob); banner.style.display = 'block'; }
      if (badge) {
        const type = activeJob.job_type === 'transcode' ? 'Transcoding' : 'Indexing';
        badge.textContent = `⏳ ${type} ${(activeJob.progress || 0).toFixed(0)}%`;
        badge.style.display = 'inline-flex';
      }
      if (btnAnalyze) {
        btnAnalyze.disabled = false;
        btnAnalyze.textContent = activeJob.job_type === 'analytics'
          ? '⏳ Indexing Active (Click to Manage)' : '⚡ Run Batch Analytics (Transcode Active)';
      }
      return;
    }
    if (banner) { banner.style.display = 'none'; banner.innerHTML = ''; }
    if (badge) { badge.style.display = 'none'; badge.textContent = ''; }
    if (btnAnalyze) { btnAnalyze.disabled = false; btnAnalyze.textContent = '⚡ Run Batch Analytics'; }
  }

  function updateSidebarCards(client) {
    document.querySelectorAll('.video-file-card').forEach((card) => {
      const fn = card.getAttribute('data-file');
      const job = fn ? client.getActiveJob(fn) : null;
      let pill = card.querySelector('.video-file-card-job-pill');
      if (job) {
        card.classList.add('job-running');
        const type = job.job_type === 'transcode' ? 'Transcode' : 'Index';
        if (!pill) {
          pill = document.createElement('span');
          pill.className = 'video-file-card-job-pill';
          const meta = card.querySelector('.video-file-meta .video-filesize');
          if (meta) meta.appendChild(pill);
        }
        if (pill) pill.textContent = `⏳ ${type} ${(job.progress || 0).toFixed(0)}%`;
      } else {
        card.classList.remove('job-running');
        if (pill && pill.parentNode) pill.parentNode.removeChild(pill);
      }
    });
  }

  function updateBackgroundPill(client) {
    const activeJobs = client.getAllActiveJobs();
    syncDrawerJobsBadge(activeJobs.length);
    let pill = document.getElementById('background-video-job-pill');
    const backgroundJob = activeJobs.find((j) => j.filename !== client.currentViewedFilename);
    if (!backgroundJob) { if (pill) pill.style.display = 'none'; return; }

    if (!pill) {
      pill = document.createElement('div');
      pill.id = 'background-video-job-pill';
      pill.className = 'glass-panel';
      Object.assign(pill.style, {
        position: 'fixed', bottom: '20px', right: '20px', zIndex: '9000',
        display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 14px',
        borderRadius: '8px', background: 'rgba(17, 24, 39, 0.92)',
        border: '1px solid rgba(59, 130, 246, 0.5)', fontSize: '0.85rem',
        color: '#e5e7eb', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.4)',
      });
      document.body.appendChild(pill);
    }

    const type = backgroundJob.job_type === 'transcode' ? 'Transcoding' : 'Indexing';
    const pct = (backgroundJob.progress || 0).toFixed(0);
    pill.style.display = 'flex';
    pill.innerHTML = `<span>⏳ <strong>${escapeHtml(backgroundJob.filename)}</strong> (${type} ${pct}%)</span><button class="btn btn-xs btn-primary btn-view-background-job" style="min-height: 26px; padding: 2px 8px; font-size: 0.75rem; cursor: pointer;">View</button>`;
    pill.querySelector('.btn-view-background-job')?.addEventListener('click', () => {
      window.dispatchEvent(new CustomEvent('video-select-request', { detail: { filename: backgroundJob.filename } }));
    });
  }

  window.VideoJobUI = {
    showConflictModal,
    closeConflictModal,
    renderProgressBar,
    renderErrorAlert,
    syncActiveJobUI,
    updateSidebarCards,
    updateBackgroundPill,
  };
})();
