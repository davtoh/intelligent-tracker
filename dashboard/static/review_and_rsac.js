/**
 * Intelligent Tracker - Milestone 9: Artifact & Face Intelligence,
 * Active Learning & Adaptive Memory Client Controller.
 *
 * Coordinates:
 * - Active Learning ("Review & Learn" Inbox) triage
 * - 1-Click Candidate confirmation, reassignment, and dismissal
 * - Telemetry alert monitoring and notification toasts
 * - Coordination of UniversalEnrollment, RSACVersions, and ReviewModals modules
 */

(function () {
  'use strict';

  const state = {
    currentReviewStatus: 'pending',
    pendingReviewCount: 0,
    lastSeenAlertIds: new Set(),
  };

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function showToast(title, body, type = 'info', actionText = null, onAction = null) {
    if (window.showToast) {
      return window.showToast(title, body, type, actionText, onAction);
    }
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast-message ${type}`;
    const actionHtml = actionText ? `<div class="toast-action">${escapeHtml(actionText)}</div>` : '';

    toast.innerHTML = `
      <div class="toast-header">
        <span class="toast-title">${escapeHtml(title)}</span>
        <button class="toast-close">&times;</button>
      </div>
      <div class="toast-body">${escapeHtml(body)}</div>
      ${actionHtml}
    `;

    toast.querySelector('.toast-close').addEventListener('click', () => toast.remove());
    if (actionText && onAction) {
      toast.querySelector('.toast-action').addEventListener('click', () => {
        onAction();
        toast.remove();
      });
    }

    container.appendChild(toast);
    setTimeout(() => { if (toast.parentElement) toast.remove(); }, 6000);
  }

  async function loadReviewQueue(status = 'pending', opts = {}) {
    state.currentReviewStatus = status;
    const container = document.getElementById('review-queue-container');
    const counter = document.getElementById('review-inbox-counter');
    if (!container) return;
    const controls = window.ReviewQueueControls;
    if (controls) controls.setState({ status, ...(opts.resetOffset ? { offset: 0 } : {}) });

    try {
      const url = controls
        ? controls.buildQueryUrl({ status })
        : `/api/review/queue?status=${encodeURIComponent(status)}&limit=50`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const items = data.items || [];
      const totalCount = typeof data.total === 'number' ? data.total : items.length;
      const pendingCount = typeof data.total_pending === 'number'
        ? data.total_pending
        : (status === 'pending' ? totalCount : state.pendingReviewCount);

      if (status === 'pending' || typeof data.total_pending === 'number') {
        state.pendingReviewCount = pendingCount;
        ['header-review-badge', 'drawer-review-badge', 'drawer-review-count'].forEach((id) => {
          const b = document.getElementById(id);
          if (b) {
            b.textContent = pendingCount;
            b.style.display = pendingCount > 0 ? 'inline-block' : 'none';
          }
        });
      }

      if (counter) {
        counter.textContent = `${totalCount} Candidate${totalCount === 1 ? '' : 's'}`;
      }

      renderReviewGrid(items, container, status);
      controls?.updatePagination?.({
        total: totalCount, totalPending: pendingCount, count: items.length,
        offset: data.offset ?? 0, limit: data.limit ?? 50, status,
      });
    } catch (err) {
      container.innerHTML = `<div class="empty-state">Failed to load review queue: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function openReviewItem(reviewId) {
    await loadReviewQueue('pending', { resetOffset: true });
    if (reviewId === undefined || reviewId === null || reviewId === '') return null;
    const container = document.getElementById('review-queue-container');
    if (window.ReviewQueueControls?.highlightReviewItem) {
      return window.ReviewQueueControls.highlightReviewItem(reviewId, {
        container, buildCardHtml: buildReviewCardHtml, bindCardButtons: bindReviewActionButtons, fetchFn: fetch,
      });
    }
    const cards = container?.querySelectorAll ? Array.from(container.querySelectorAll('.review-card')) : [];
    const card = cards.find((el) => String(el.getAttribute?.('data-item-id') ?? '') === String(reviewId)) || null;
    card?.classList?.add?.('review-card-highlight');
    return card;
  }

  function normalizeCropUrl(item) {
    const raw = item?.crop_url || item?.crop_path || '';
    if (!raw) return '/static/avatar-placeholder.svg';
    if (raw.startsWith('/crops/') || raw.startsWith('http') || raw.startsWith('data:')) return raw;
    const base = String(raw).split(/[\\/]/).pop();
    return base ? `/crops/${encodeURIComponent(base)}` : '/static/avatar-placeholder.svg';
  }

  function formatReviewTimestamp(rawTs) {
    if (rawTs === null || rawTs === undefined || rawTs === '') return '';
    const num = Number(rawTs);
    if (Number.isFinite(num) && num > 0) return new Date(num * 1000).toLocaleString();
    return String(rawTs);
  }

  function buildProvenanceHtml(item) {
    const parts = [];
    if (item.video_filename) {
      const offset = Number(item.media_offset_sec || 0).toFixed(1);
      parts.push(`<span class="review-source-pill">Video: ${escapeHtml(item.video_filename)} @ ${offset}s</span>`);
    } else if (item.camera_id) {
      parts.push(`<span class="review-source-pill">Live: ${escapeHtml(item.camera_id)}</span>`);
    }
    if (item.run_id) {
      parts.push(`<span class="review-run-pill">Run: ${escapeHtml(item.run_id)}</span>`);
    }
    let bbox = item.bbox;
    if (!bbox && item.bbox_json) {
      try { bbox = JSON.parse(item.bbox_json); } catch (_) { bbox = null; }
    }
    if (Array.isArray(bbox) && bbox.length === 4) {
      const dims = item.frame_width && item.frame_height ? ` (${item.frame_width}x${item.frame_height})` : '';
      parts.push(`<span class="review-bbox-badge">bbox [${bbox.map(Number).join(', ')}]${dims}</span>`);
    }
    return parts.length ? `<div class="review-provenance-row">${parts.join('')}</div>` : '';
  }

  function buildReviewCardHtml(item) {
    const sim = (item.similarity ?? item.similarity_score ?? 0) * 100;
    const simColor = sim >= 60 ? '#06b6d4' : '#f59e0b';
    const cropUrl = normalizeCropUrl(item);
    const suggested = item.suggested_name ?? item.matched_entity_name;
    const matchLabel = suggested ? `Matched: <strong>${escapeHtml(suggested)}</strong>` : 'Unidentified Borderline Track';
    const tsText = formatReviewTimestamp(item.timestamp ?? item.created_at);
    const seekBtn = window.VideoTimelineLinks?.buildSeekInStudioButtonHtml(item.video_filename, item.media_offset_sec) || '';
    const jumpBtns = window.VideoTimelineLinks?.buildSourceJumpButtonsHtml?.({
      cameraId: item.camera_id, videoFilename: item.video_filename, runId: item.run_id,
      mediaOffsetSec: item.media_offset_sec, trackId: item.track_id, entityId: item.matched_entity_id,
    }, { includeVideo: false }) || '';
    const linkRow = [seekBtn, jumpBtns].filter(Boolean).join(' ');
    const provenanceHtml = buildProvenanceHtml(item);
    const reasonBadge = window.ReviewUndoAndFlag?.renderReasonBadgeHtml?.(item) || '';
    const cardUndoBtn = window.ReviewUndoAndFlag?.renderCardUndoButtonHtml?.(item) || '';
    const actionsHtml = item.status === 'pending'
      ? `<div class="review-actions">
          <button class="btn btn-xs btn-confirm" data-id="${item.id}" data-name="${escapeHtml(suggested || '')}" title="Confirm as Ground Truth Locked Anchor">✓ Confirm (Locked Anchor)</button>
          <button class="btn btn-xs btn-reassign" data-id="${item.id}" title="Reassign signature to a different entity">🟨 Reassign</button>
          <button class="btn btn-xs btn-enroll-new" data-id="${item.id}" data-crop="${escapeHtml(cropUrl)}" title="Enroll as a newly created entity">✨ Enroll New</button>
          <button class="btn btn-xs btn-dismiss" data-id="${item.id}" title="Dismiss candidate without changes">✕ Dismiss</button>
        </div>`
      : `<div class="review-resolved-row" style="display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:11px;color:#94a3b8;font-style:italic;"><span>Status: <span style="color:#f8fafc;font-weight:600;">${escapeHtml(item.status)}</span>${item.notes ? ` &mdash; ${escapeHtml(item.notes)}` : ''}</span>${cardUndoBtn}</div>`;
    return `
      <div class="glass-panel review-card" data-item-id="${item.id}">
        <div class="review-card-top">
          <img class="review-thumb" src="${cropUrl}" alt="Review Crop" onerror="this.onerror=null;this.src='/static/avatar-placeholder.svg';" />
          <div class="review-meta">
            <div class="review-title">Track #${item.track_id} (${escapeHtml(item.camera_id)}) ${reasonBadge}</div>
            <div class="review-candidate-match">${matchLabel}</div>
            <div class="confidence-meter">
              <span>Confidence:</span>
              <div class="confidence-bar-track"><div class="confidence-bar-fill" style="width: ${Math.min(100, Math.max(5, sim))}%; background: ${simColor};"></div></div>
              <span style="font-weight: 600; color: ${simColor};">${sim.toFixed(1)}%</span>
            </div>
            <div class="review-timestamp">${escapeHtml(tsText)}</div>
            ${provenanceHtml}
            ${linkRow ? `<div class="review-seek-row">${linkRow}</div>` : ''}
          </div>
        </div>
        ${actionsHtml}
      </div>`;
  }

  function renderReviewGrid(items, container, status) {
    if (!items.length) {
      container.innerHTML = `<div class="empty-state">No ${escapeHtml(status)} candidates in review queue. Borderline matches (0.45 &lt; sim &lt; 0.70) are automatically routed here.</div>`;
      return;
    }
    container.innerHTML = items.map(buildReviewCardHtml).join('');
    bindReviewActionButtons(container);
  }

  function bindReviewActionButtons(container) {
    container.querySelectorAll('.btn-confirm').forEach(btn => {
      btn.addEventListener('click', () => confirmReviewItem(btn.getAttribute('data-id'), btn.getAttribute('data-name') || ''));
    });
    container.querySelectorAll('.btn-reassign').forEach(btn => {
      btn.addEventListener('click', () => window.ReviewModals?.openReassignModal(btn.getAttribute('data-id')));
    });
    container.querySelectorAll('.btn-enroll-new').forEach(btn => {
      btn.addEventListener('click', () => window.ReviewModals?.enrollNewFromReview(btn.getAttribute('data-id')));
    });
    container.querySelectorAll('.btn-dismiss').forEach(btn => {
      btn.addEventListener('click', () => dismissReviewItem(btn.getAttribute('data-id')));
    });
    window.ReviewUndoAndFlag?.bindCardUndoButtons?.(container);
  }

  function notifyReviewResolved(data) {
    window.ReviewUndoAndFlag?.recordResolvedDecision?.(data);
    const syncFn = data?.sync?.video_filename;
    if (syncFn) {
      window.VideoBatchReports?.invalidateCachedReports?.(syncFn);
      if (window.VideoBatchReports?.getCurrentFilename?.() === syncFn) {
        window.VideoBatchReports?.restoreReportForFile?.(syncFn);
      }
      window.OverlayLayers?.ensureLoaded?.(syncFn, { force: true });
    }
    window.loadGallery?.() || window.GalleryTimeline?.loadGallery?.();
    loadReviewQueue(state.currentReviewStatus);
  }

  async function confirmReviewItem(itemId, name = '') {
    try {
      const res = await fetch(`/api/review/${itemId}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: 'Operator verified ground-truth locked anchor' }),
      });
      if (!res.ok) throw new Error('Confirm failed');
      const data = await res.json();
      showToast('Candidate Confirmed', `Locked as ground truth anchor for ${data.entity_name || name || 'entity'}.`, 'success');
      notifyReviewResolved(data);
    } catch (err) {
      showToast('Confirmation Error', err.message, 'error');
    }
  }

  async function dismissReviewItem(itemId) {
    try {
      const res = await fetch(`/api/review/${itemId}/dismiss`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: 'Operator dismissed borderline candidate' }),
      });
      if (!res.ok) throw new Error('Dismiss failed');
      const data = await res.json().catch(() => ({}));
      showToast('Candidate Dismissed', 'Review item dismissed without modifying gallery.', 'info');
      notifyReviewResolved(data);
    } catch (err) {
      showToast('Dismissal Error', err.message, 'error');
    }
  }

  function checkAlertEvents(alerts) {
    if (!alerts || !Array.isArray(alerts)) return;

    alerts.forEach(ev => {
      const evId = ev.id || `${ev.event_type}_${ev.timestamp}_${ev.track_id || ''}`;
      if (state.lastSeenAlertIds.has(evId)) return;
      state.lastSeenAlertIds.add(evId);

      if (ev.event_type === 'review_item_queued') {
        const sim = (ev.similarity || 0) * 100;
        const ref = ev.review_id != null ? { reviewId: ev.review_id } : {};
        showToast(
          '🧠 Review Candidate Queued',
          `Borderline match (${sim.toFixed(1)}%) for track #${ev.track_id} (${ev.camera_id}).`,
          'review',
          'Review Candidate',
          () => {
            if (window.App?.navigate) return window.App.navigate('tab-review', ref);
            if (window.AppNavigation?.navigate) return window.AppNavigation.navigate('tab-review', ref);
            document.getElementById('tab-btn-review')?.click();
          }
        );
        loadReviewQueue(state.currentReviewStatus);
      } else if (ev.event_type === 'rsac_violation') {
        showToast(
          '🚨 Access Control Violation',
          `${ev.entity_name || 'Entity'} unauthorized in zone '${ev.zone_id}' (${ev.camera_id}).`,
          'alert',
          'View Alerts',
          () => {
            const btn = document.getElementById('tab-btn-alerts');
            if (btn) btn.click();
          }
        );
      }
    });

    if (state.lastSeenAlertIds.size > 200) {
      const arr = Array.from(state.lastSeenAlertIds).slice(-100);
      state.lastSeenAlertIds = new Set(arr);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    window.UniversalEnrollment?.init();
    window.ReviewModals?.initReassignModal((data) => notifyReviewResolved(data));
    window.ReviewModals?.initQuickEnrollModal((data) => notifyReviewResolved(data));
    window.RSACVersions?.init();
    window.ReviewQueueControls?.bindControls?.(() => loadReviewQueue(state.currentReviewStatus), showToast);

    document.querySelectorAll('.review-filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.review-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        loadReviewQueue(btn.getAttribute('data-status'), { resetOffset: true });
      });
    });

    document.getElementById('btn-refresh-review-queue')?.addEventListener('click', () => {
      loadReviewQueue(state.currentReviewStatus);
    });

    if (!/[?&]review_id=/.test(window.location?.hash || '')) loadReviewQueue('pending');
  });

  window.ReviewAndRSAC = {
    loadQueue: loadReviewQueue,
    openReviewItem,
    openVersionsModal: (entityId, entityName) => window.RSACVersions?.openVersionsModal(entityId, entityName),
    checkAlertEvents,
    showToast,
  };
})();
