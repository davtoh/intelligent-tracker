/**
 * Intelligent Tracker - Video Job Client & UI Coordinator.
 * Manages asynchronous video transcoding and occurrence indexing jobs,
 * polling loops, interactive cancellation modals, and progress rendering.
 */

(function () {
  'use strict';

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
      const viewed = this.currentViewedFilename;
      const eventFile = data && !Array.isArray(data) ? data.filename : null;
      if (!eventFile || !viewed || eventFile === viewed || this.getActiveJob(viewed)?.filename === eventFile) {
        this.syncActiveJobUI(viewed);
      }
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
      const force = Boolean(options.force);

      const resp = await fetch(
        `/api/videos/${encodeURIComponent(filename)}/transcode?async_mode=true&target_resolution=${encodeURIComponent(targetRes)}&force=${force}`,
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
      window.VideoJobUI?.showConflictModal(this, activeJob, targetActionName, onCancelAndProceed, onKeepRunning);
    }

    closeConflictModal() {
      window.VideoJobUI?.closeConflictModal();
    }

    renderProgressBar(container, job, onCancelClick) {
      window.VideoJobUI?.renderProgressBar(this, container, job, onCancelClick);
    }

    renderErrorAlert(container, errorText, onRetry) {
      window.VideoJobUI?.renderErrorAlert(container, errorText, onRetry);
    }

    syncActiveJobUI(filename) {
      window.VideoJobUI?.syncActiveJobUI(this, filename);
    }

    updateSidebarCards() {
      window.VideoJobUI?.updateSidebarCards(this);
    }

    updateBackgroundPill() {
      window.VideoJobUI?.updateBackgroundPill(this);
    }
  }

  // Global singleton
  window.VideoJobClient = new VideoJobClient();
  window.VideoJobClient.init();
})();

