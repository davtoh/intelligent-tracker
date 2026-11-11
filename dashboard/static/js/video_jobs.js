/**
 * Intelligent Tracker - Video Job Client & UI Coordinator.
 * Manages asynchronous video transcoding and occurrence indexing jobs,
 * polling loops, interactive cancellation modals, and progress rendering.
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

  class VideoJobClient {
    constructor() {
      this.jobsByFilename = new Map();
      this.pollingTimer = null;
      this.isPolling = false;
      this.currentViewedFilename = null;
      this.listeners = new Set();
    }

    init() {
      this.refreshActiveJobs();
      window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') this.closeConflictModal();
      });
    }

    setCurrentViewedFilename(filename) {
      this.currentViewedFilename = filename ? String(filename).trim() : null;
      this.syncActiveJobUI(this.currentViewedFilename);
      this.updateBackgroundPill();
      this.updateSidebarCards();
    }

    subscribe(fn) {
      if (typeof fn === 'function') {
        this.listeners.add(fn);
        return () => this.listeners.delete(fn);
      }
      return () => {};
    }

    _notify(eventType, data) {
      this.syncActiveJobUI(this.currentViewedFilename);
      this.updateSidebarCards();
      this.listeners.forEach(fn => {
        try { fn(eventType, data); } catch (e) { console.debug('Listener error:', e); }
      });
      window.dispatchEvent(new CustomEvent('video-job-event', { detail: { type: eventType, data } }));
    }

    getActiveJob(filename) {
      if (!filename) return null;
      const job = this.jobsByFilename.get(filename);
      if (job && (job.status === 'pending' || job.status === 'running')) {
        return job;
      }
      // Also check related variant (e.g. base.mp4 vs base_h264.mp4)
      const base = filename.replace(/_h264(\.[^.]+)$/, '$1');
      for (const j of this.jobsByFilename.values()) {
        if (j.status === 'pending' || j.status === 'running') {
          const jBase = j.filename.replace(/_h264(\.[^.]+)$/, '$1');
          if (jBase === base) return j;
        }
      }
      return null;
    }

    getAllActiveJobs() {
      const active = [];
      for (const job of this.jobsByFilename.values()) {
        if (job.status === 'pending' || job.status === 'running') {
          active.push(job);
        }
      }
      return active;
    }

    async refreshActiveJobs() {
      try {
        const resp = await fetch('/api/videos/jobs?active_only=true');
        if (resp.ok) {
          const list = await resp.json();
          this.jobsByFilename.clear();
          list.forEach(j => this.jobsByFilename.set(j.filename, j));
          this._checkPollingState();
          this.updateBackgroundPill();
          this._notify('refresh', list);
        }
      } catch (e) {
        console.debug('Error refreshing active jobs:', e);
      }
    }

    _checkPollingState() {
      const hasActive = this.getAllActiveJobs().length > 0;
      if (hasActive && !this.isPolling) {
        this.isPolling = true;
        this.pollingTimer = setInterval(() => this._poll(), 1000);
      } else if (!hasActive && this.isPolling) {
        this.isPolling = false;
        if (this.pollingTimer) {
          clearInterval(this.pollingTimer);
          this.pollingTimer = null;
        }
      }
    }

    async _poll() {
      const activeJobs = this.getAllActiveJobs();
      if (activeJobs.length === 0) {
        this._checkPollingState();
        return;
      }

      for (const job of activeJobs) {
        try {
          const resp = await fetch(`/api/videos/jobs/${encodeURIComponent(job.job_id)}`);
          if (resp.ok) {
            const updated = await resp.json();
            this.jobsByFilename.set(updated.filename, updated);
            this._notify('job-update', updated);
            if (updated.status === 'completed' || updated.status === 'failed' || updated.status === 'cancelled') {
              this._notify('job-finished', updated);
            }
          }
        } catch (e) {
          console.debug('Error polling job ' + job.job_id, e);
        }
      }
      this._checkPollingState();
      this.updateBackgroundPill();
    }

    async startTranscode(filename, options = {}) {
      if (!filename) throw new Error('Missing filename');
      const targetRes = options.targetResolution || '1080p';

      const resp = await fetch(
        `/api/videos/${encodeURIComponent(filename)}/transcode?async_mode=true&target_resolution=${encodeURIComponent(targetRes)}`,
        { method: 'POST' }
      );

      if (resp.status === 409) {
        const conflict = await resp.json();
        return new Promise((resolve, reject) => {
          this.showConflictModal(conflict.active_job, 'Convert to H.264', async () => {
            try {
              const retryResp = await this.startTranscode(filename, options);
              resolve(retryResp);
            } catch (err) { reject(err); }
          }, () => reject(new Error('User kept existing job running')));
        });
      }

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || err.message || 'Transcode request failed');
      }

      const data = await resp.json();
      if (data.job) {
        this.jobsByFilename.set(data.job.filename, data.job);
        this._checkPollingState();
        this._notify('job-started', data.job);
      }
      return data;
    }

    async startAnalytics(filename, payload = {}) {
      if (!filename) throw new Error('Missing filename');
      const queryParams = new URLSearchParams({ async_mode: 'true' });
      if (payload.sample_rate) queryParams.set('sample_rate', payload.sample_rate);
      if (payload.detector) queryParams.set('detector', payload.detector);
      if (payload.confidence !== undefined) queryParams.set('confidence', payload.confidence);

      const resp = await fetch(
        `/api/videos/${encodeURIComponent(filename)}/analyze?${queryParams.toString()}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      );

      if (resp.status === 409) {
        const conflict = await resp.json();
        return new Promise((resolve, reject) => {
          this.showConflictModal(conflict.active_job, 'Batch Video Analytics', async () => {
            try {
              const retryResp = await this.startAnalytics(filename, payload);
              resolve(retryResp);
            } catch (err) { reject(err); }
          }, () => reject(new Error('User kept existing job running')));
        });
      }

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || err.message || 'Analytics request failed');
      }

      const data = await resp.json();
      if (data.job) {
        this.jobsByFilename.set(data.job.filename, data.job);
        this._checkPollingState();
        this._notify('job-started', data.job);
      }
      return data;
    }

    async cancelJob(jobId) {
      if (!jobId) return false;
      try {
        const resp = await fetch(`/api/videos/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
        if (resp.ok) {
          for (const [fn, j] of this.jobsByFilename.entries()) {
            if (j.job_id === jobId) {
              j.status = 'cancelled';
              j.stage = 'cancelled';
              this._notify('job-update', j);
              this._notify('job-finished', j);
              break;
            }
          }
          return true;
        }
      } catch (e) {
        console.error('Failed to cancel job:', e);
      }
      return false;
    }

    showConflictModal(activeJob, targetActionName, onCancelAndProceed, onKeepRunning) {
      this.closeConflictModal();
      const modal = document.createElement('div');
      modal.id = 'modal-job-conflict';
      modal.className = 'modal-backdrop';
      modal.style.position = 'fixed';
      modal.style.inset = '0';
      modal.style.zIndex = '9999';
      modal.style.background = 'rgba(0, 0, 0, 0.7)';
      modal.style.display = 'flex';
      modal.style.alignItems = 'center';
      modal.style.justifyContent = 'center';

      const typeLabel = activeJob.job_type === 'transcode' ? 'Convert to H.264' : 'Batch Video Analytics';
      const pct = (activeJob.progress || 0).toFixed(1);

      modal.innerHTML = `
        <div class="modal-dialog glass-panel" style="max-width: 460px; width: 92%; margin: auto; padding: 20px; border-radius: 10px; background: rgba(17, 24, 39, 0.95); border: 1px solid rgba(255, 255, 255, 0.15); box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <h3 style="margin: 0; font-size: 1.15rem; color: #f59e0b; display: flex; align-items: center; gap: 8px;">
              <span>⚠️</span> Task in Progress
            </h3>
            <button id="btn-conflict-close" style="background: none; border: none; color: #9ca3af; font-size: 1.25rem; cursor: pointer; padding: 4px 8px; min-height: 32px; min-width: 32px;">✕</button>
          </div>
          <div style="font-size: 0.9rem; color: #e5e7eb; line-height: 1.5; margin-bottom: 16px;">
            <p style="margin: 0 0 10px 0;">
              A <strong>${escapeHtml(typeLabel)}</strong> job is currently running on <span style="color: #60a5fa; font-family: monospace;">${escapeHtml(activeJob.filename)}</span>.
            </p>
            <div style="background: rgba(0, 0, 0, 0.35); padding: 10px; border-radius: 6px; margin-bottom: 10px;">
              <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: #9ca3af; margin-bottom: 6px;">
                <span>Progress: ${pct}%</span>
                <span>Stage: ${escapeHtml(activeJob.stage || 'running')}</span>
              </div>
              <div style="width: 100%; height: 8px; background: rgba(255, 255, 255, 0.1); border-radius: 4px; overflow: hidden;">
                <div style="width: ${pct}%; height: 100%; background: #3b82f6; transition: width 0.3s ease;"></div>
              </div>
            </div>
            <p style="margin: 0; color: #9ca3af; font-size: 0.85rem;">
              Cancel this job to start <strong>${escapeHtml(targetActionName)}</strong>, or keep the existing job running?
            </p>
          </div>
          <div style="display: flex; justify-content: flex-end; gap: 10px;">
            <button id="btn-conflict-keep" class="btn btn-secondary" style="min-height: 36px; padding: 6px 14px; border-radius: 6px; cursor: pointer;">Keep Running</button>
            <button id="btn-conflict-cancel-proceed" class="btn btn-danger" style="min-height: 36px; padding: 6px 14px; border-radius: 6px; cursor: pointer; background: #dc2626; color: white; border: none;">Cancel &amp; Proceed</button>
          </div>
        </div>
      `;

      document.body.appendChild(modal);

      const close = () => this.closeConflictModal();
      modal.querySelector('#btn-conflict-close')?.addEventListener('click', () => { close(); if (onKeepRunning) onKeepRunning(); });
      modal.querySelector('#btn-conflict-keep')?.addEventListener('click', () => { close(); if (onKeepRunning) onKeepRunning(); });
      modal.querySelector('#btn-conflict-cancel-proceed')?.addEventListener('click', async () => {
        const btn = modal.querySelector('#btn-conflict-cancel-proceed');
        if (btn) { btn.disabled = true; btn.textContent = 'Cancelling...'; }
        await this.cancelJob(activeJob.job_id);
        close();
        if (onCancelAndProceed) onCancelAndProceed();
      });
    }

    closeConflictModal() {
      const modal = document.getElementById('modal-job-conflict');
      if (modal && modal.parentNode) {
        modal.parentNode.removeChild(modal);
      }
    }

    renderProgressBar(container, job, onCancelClick) {
      if (!container || !job) return;
      const isTranscode = job.job_type === 'transcode';
      const label = isTranscode ? '⚡ Converting to H.264...' : '🧠 Indexing Batch Occurrences...';
      const pct = Math.min(100, Math.max(0, job.progress || 0)).toFixed(1);
      const metrics = job.metrics || {};

      let subtext = '';
      if (isTranscode) {
        const fps = metrics.fps ? `${metrics.fps} FPS` : '';
        const elapsed = metrics.elapsed ? `${metrics.elapsed}s` : '';
        subtext = [fps, elapsed].filter(Boolean).join(' • ');
      } else {
        const frames = metrics.total_frames ? `${metrics.read_frames || 0}/${metrics.total_frames} frames` : '';
        const sightings = metrics.sightings ? `${metrics.sightings} sightings` : '';
        const speed = metrics.fps ? `${metrics.fps} FPS` : '';
        subtext = [frames, sightings, speed].filter(Boolean).join(' • ');
      }

      container.innerHTML = `
        <div class="video-job-progress-panel glass-panel" style="padding: 10px 14px; margin-bottom: 12px; border-radius: 8px; background: rgba(59, 130, 246, 0.12); border: 1px solid rgba(59, 130, 246, 0.4);">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="color: #60a5fa; font-weight: 600; font-size: 0.85rem;">${escapeHtml(label)}</span>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-weight: 700; font-size: 0.85rem; color: #e5e7eb;">${pct}%</span>
              <button class="btn btn-xs btn-danger btn-cancel-active-job" style="min-height: 28px; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; cursor: pointer; background: #dc2626; color: white; border: none;">✖ Cancel</button>
            </div>
          </div>
          <div style="width: 100%; height: 8px; background: rgba(255, 255, 255, 0.1); border-radius: 4px; overflow: hidden;">
            <div style="width: ${pct}%; height: 100%; background: #3b82f6; border-radius: 4px; transition: width 0.3s ease;"></div>
          </div>
          ${subtext ? `<div style="font-size: 0.75rem; color: #9ca3af; margin-top: 6px;">${escapeHtml(subtext)}</div>` : ''}
        </div>
      `;

      container.querySelector('.btn-cancel-active-job')?.addEventListener('click', () => {
        if (onCancelClick) {
          onCancelClick(job);
        } else {
          this.cancelJob(job.job_id);
        }
      });
    }

    renderErrorAlert(container, errorText, onRetry) {
      if (!container) return;
      container.innerHTML = `
        <div class="video-job-error-alert glass-panel" style="padding: 10px 14px; margin-bottom: 12px; border-radius: 8px; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.4); display: flex; align-items: center; justify-content: space-between;">
          <div style="color: #ef4444; font-size: 0.85rem; flex: 1; padding-right: 10px;">
            <strong>⚠️ Task Failed:</strong> ${escapeHtml(errorText || 'Unknown error occurred')}
          </div>
          ${onRetry ? `<button class="btn btn-xs btn-secondary btn-retry-job" style="min-height: 28px; padding: 2px 10px; font-size: 0.75rem; cursor: pointer;">↻ Retry</button>` : ''}
        </div>
      `;
      if (onRetry) {
        container.querySelector('.btn-retry-job')?.addEventListener('click', onRetry);
      }
    }

    syncActiveJobUI(filename) {
      const banner = document.getElementById('scrubber-active-job-banner');
      const badge = document.getElementById('scrubber-header-job-badge');
      const btnAnalyze = document.getElementById('btn-video-analyze');
      if (!filename) {
        if (banner) { banner.style.display = 'none'; banner.innerHTML = ''; }
        if (badge) { badge.style.display = 'none'; badge.textContent = ''; }
        return;
      }

      const activeJob = this.getActiveJob(filename);
      window.VideoBatch?.syncContainerVisibility?.(filename);
      if (activeJob) {
        if (banner) {
          this.renderProgressBar(banner, activeJob);
          banner.style.display = 'block';
        }
        if (badge) {
          const type = activeJob.job_type === 'transcode' ? 'Transcoding' : 'Indexing';
          badge.textContent = `⏳ ${type} ${(activeJob.progress || 0).toFixed(0)}%`;
          badge.style.display = 'inline-flex';
        }
        if (btnAnalyze) {
          btnAnalyze.disabled = false;
          btnAnalyze.textContent = activeJob.job_type === 'analytics'
            ? '⏳ Indexing Active (Click to Manage)'
            : '⚡ Run Batch Analytics (Transcode Active)';
        }
      } else {
        if (banner) {
          banner.style.display = 'none';
          banner.innerHTML = '';
        }
        if (badge) {
          badge.style.display = 'none';
          badge.textContent = '';
        }
        if (btnAnalyze && filename) {
          btnAnalyze.disabled = false;
          btnAnalyze.textContent = '⚡ Run Batch Analytics';
        }
      }
    }

    updateSidebarCards() {
      document.querySelectorAll('.video-file-card').forEach(card => {
        const fn = card.getAttribute('data-file');
        const job = fn ? this.getActiveJob(fn) : null;
        let pill = card.querySelector('.video-file-card-job-pill');
        if (job) {
          card.classList.add('job-running');
          const type = job.job_type === 'transcode' ? 'Transcode' : 'Index';
          const pct = (job.progress || 0).toFixed(0);
          if (!pill) {
            pill = document.createElement('span');
            pill.className = 'video-file-card-job-pill';
            const meta = card.querySelector('.video-file-meta .video-filesize');
            if (meta) meta.appendChild(pill);
          }
          if (pill) {
            pill.textContent = `⏳ ${type} ${pct}%`;
          }
        } else {
          card.classList.remove('job-running');
          if (pill && pill.parentNode) {
            pill.parentNode.removeChild(pill);
          }
        }
      });
    }

    updateBackgroundPill() {
      let pill = document.getElementById('background-video-job-pill');
      const activeJobs = this.getAllActiveJobs();

      // Find an active job on a file other than the currently viewed one
      const backgroundJob = activeJobs.find(j => j.filename !== this.currentViewedFilename);

      if (!backgroundJob) {
        if (pill) pill.style.display = 'none';
        return;
      }

      if (!pill) {
        pill = document.createElement('div');
        pill.id = 'background-video-job-pill';
        pill.className = 'glass-panel';
        pill.style.position = 'fixed';
        pill.style.bottom = '20px';
        pill.style.right = '20px';
        pill.style.zIndex = '9000';
        pill.style.display = 'flex';
        pill.style.alignItems = 'center';
        pill.style.gap = '10px';
        pill.style.padding = '8px 14px';
        pill.style.borderRadius = '8px';
        pill.style.background = 'rgba(17, 24, 39, 0.92)';
        pill.style.border = '1px solid rgba(59, 130, 246, 0.5)';
        pill.style.fontSize = '0.85rem';
        pill.style.color = '#e5e7eb';
        pill.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.4)';
        document.body.appendChild(pill);
      }

      const type = backgroundJob.job_type === 'transcode' ? 'Transcoding' : 'Indexing';
      const pct = (backgroundJob.progress || 0).toFixed(0);

      pill.style.display = 'flex';
      pill.innerHTML = `
        <span>⏳ <strong>${escapeHtml(backgroundJob.filename)}</strong> (${type} ${pct}%)</span>
        <button class="btn btn-xs btn-primary btn-view-background-job" style="min-height: 26px; padding: 2px 8px; font-size: 0.75rem; cursor: pointer;">View</button>
      `;

      pill.querySelector('.btn-view-background-job')?.addEventListener('click', () => {
        window.dispatchEvent(new CustomEvent('video-select-request', { detail: { filename: backgroundJob.filename } }));
      });
    }
  }

  // Global singleton
  window.VideoJobClient = new VideoJobClient();
  window.VideoJobClient.init();
})();

