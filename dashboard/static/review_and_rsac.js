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

  async function loadReviewQueue(status = 'pending') {
    state.currentReviewStatus = status;
    const container = document.getElementById('review-queue-container');
    const counter = document.getElementById('review-inbox-counter');
    const badge = document.getElementById('header-review-badge');

    if (!container) return;

    try {
      const res = await fetch(`/api/active-learning/queue?status=${encodeURIComponent(status)}&limit=50`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const items = data.items || [];

      if (status === 'pending') {
        state.pendingReviewCount = items.length;
        if (badge) {
          badge.textContent = items.length;
          badge.style.display = items.length > 0 ? 'inline-block' : 'none';
        }
      }

      if (counter) {
        counter.textContent = `${items.length} Candidate${items.length === 1 ? '' : 's'}`;
      }

      renderReviewGrid(items, container, status);
    } catch (err) {
      container.innerHTML = `<div class="empty-state">Failed to load review queue: ${escapeHtml(err.message)}</div>`;
    }
  }

  function renderReviewGrid(items, container, status) {
    if (!items.length) {
      container.innerHTML = `
        <div class="empty-state">
          No ${escapeHtml(status)} candidates in review queue. Borderline matches (0.45 &lt; sim &lt; 0.70) are automatically routed here.
        </div>
      `;
      return;
    }

    container.innerHTML = items.map(item => {
      const sim = (item.similarity_score || 0) * 100;
      const simColor = sim >= 60 ? '#06b6d4' : '#f59e0b';
      const cropUrl = item.crop_path ? (item.crop_path.startsWith('/') ? item.crop_path : `/${item.crop_path}`) : '/static/avatar-placeholder.png';
      const matchLabel = item.matched_entity_name ? `Matched: <strong>${escapeHtml(item.matched_entity_name)}</strong>` : 'Unidentified Borderline Track';
      const isPending = item.status === 'pending';

      const actionsHtml = isPending ? `
        <div class="review-actions">
          <button class="btn btn-xs btn-confirm" data-id="${item.id}" title="Confirm as Ground Truth Locked Anchor">
            ✓ Confirm (Locked Anchor)
          </button>
          <button class="btn btn-xs btn-reassign" data-id="${item.id}" title="Reassign signature to a different entity">
            🟨 Reassign
          </button>
          <button class="btn btn-xs btn-enroll-new" data-id="${item.id}" data-crop="${escapeHtml(cropUrl)}" title="Enroll as a newly created entity">
            ✨ Enroll New
          </button>
          <button class="btn btn-xs btn-dismiss" data-id="${item.id}" title="Dismiss candidate without changes">
            ✕ Dismiss
          </button>
        </div>
      ` : `
        <div style="font-size: 11px; color: #94a3b8; font-style: italic;">
          Status: <span style="color: #f8fafc; font-weight: 600;">${escapeHtml(item.status)}</span>
          ${item.notes ? ` &mdash; ${escapeHtml(item.notes)}` : ''}
        </div>
      `;

      return `
        <div class="glass-panel review-card" data-item-id="${item.id}">
          <div class="review-card-top">
            <img class="review-thumb" src="${cropUrl}" alt="Review Crop" onerror="this.src='/static/avatar-placeholder.png';" />
            <div class="review-meta">
              <div class="review-title">Track #${item.track_id} (${escapeHtml(item.camera_id)})</div>
              <div class="review-candidate-match">${matchLabel}</div>
              <div class="confidence-meter">
                <span>Confidence:</span>
                <div class="confidence-bar-track">
                  <div class="confidence-bar-fill" style="width: ${Math.min(100, Math.max(5, sim))}%; background: ${simColor};"></div>
                </div>
                <span style="font-weight: 600; color: ${simColor};">${sim.toFixed(1)}%</span>
              </div>
              <div class="review-timestamp">${escapeHtml(item.created_at)}</div>
            </div>
          </div>
          ${actionsHtml}
        </div>
      `;
    }).join('');

    bindReviewActionButtons(container);
  }

  function bindReviewActionButtons(container) {
    container.querySelectorAll('.btn-confirm').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        await confirmReviewItem(id);
      });
    });

    container.querySelectorAll('.btn-reassign').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        window.ReviewModals?.openReassignModal(id);
      });
    });

    container.querySelectorAll('.btn-enroll-new').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        window.ReviewModals?.enrollNewFromReview(id);
      });
    });

    container.querySelectorAll('.btn-dismiss').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        await dismissReviewItem(id);
      });
    });
  }

  async function confirmReviewItem(itemId) {
    try {
      const res = await fetch(`/api/active-learning/${itemId}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: 'Operator verified ground-truth locked anchor' }),
      });
      if (!res.ok) throw new Error('Confirm failed');
      const data = await res.json();
      showToast('Candidate Confirmed', `Locked as ground truth anchor for ${data.entity_name || 'entity'}.`, 'success');
      loadReviewQueue(state.currentReviewStatus);
    } catch (err) {
      showToast('Confirmation Error', err.message, 'error');
    }
  }

  async function dismissReviewItem(itemId) {
    try {
      const res = await fetch(`/api/active-learning/${itemId}/dismiss`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: 'Operator dismissed borderline candidate' }),
      });
      if (!res.ok) throw new Error('Dismiss failed');
      showToast('Candidate Dismissed', 'Review item dismissed without modifying gallery.', 'info');
      loadReviewQueue(state.currentReviewStatus);
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
        showToast(
          '🧠 Review Candidate Queued',
          `Borderline match (${sim.toFixed(1)}%) for track #${ev.track_id} (${ev.camera_id}).`,
          'review',
          'Review Candidate',
          () => {
            const btn = document.getElementById('tab-btn-review');
            if (btn) btn.click();
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
    window.ReviewModals?.initReassignModal(() => loadReviewQueue(state.currentReviewStatus));
    window.ReviewModals?.initQuickEnrollModal(() => loadReviewQueue(state.currentReviewStatus));
    window.RSACVersions?.init();

    document.querySelectorAll('.review-filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.review-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const st = btn.getAttribute('data-status');
        loadReviewQueue(st);
      });
    });

    document.getElementById('btn-refresh-review-queue')?.addEventListener('click', () => {
      loadReviewQueue(state.currentReviewStatus);
    });

    loadReviewQueue('pending');
  });

  const ReviewAndRSAC = {
    loadQueue: loadReviewQueue,
    openVersionsModal: (entityId, entityName) => window.RSACVersions?.openVersionsModal(entityId, entityName),
    checkAlertEvents: checkAlertEvents,
    showToast: showToast,
  };

  window.ReviewAndRSAC = ReviewAndRSAC;
  window.ReviewAndRSAC.checkAlertEvents = checkAlertEvents;
  window.ReviewAndRSAC.openVersionsModal = (entityId, entityName) => window.RSACVersions?.openVersionsModal(entityId, entityName);
})();
