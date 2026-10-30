/**
 * Intelligent Tracker - Active Learning Review Queue & RSAC Management Controller.
 * Coordinates human-in-the-loop review of ambiguous track embeddings, reassignments,
 * and delegates Universal Enrollment & Descriptor Versions to sub-controllers.
 */

window.ReviewAndRSAC = window.ReviewAndRSAC || {};

(function () {
  'use strict';

  const escapeHtml = window.escapeHtml || (s => s);
  const showToast = window.showToast || ((m, t) => console.log(m, t));

  const state = {
    currentReviewStatus: 'pending',
    pendingItems: [],
    recentAlertsSeen: new Set(),
  };

  async function loadReviewQueue(status = 'pending') {
    state.currentReviewStatus = status;
    const container = document.getElementById('review-queue-container');
    const badge = document.getElementById('review-inbox-badge');
    const drawerBadge = document.getElementById('drawer-review-badge');

    if (!container) return;
    container.innerHTML = '<div class="loading-state">⏳ Loading Active Learning review queue...</div>';

    try {
      const res = await fetch(`/api/active-learning/queue?status=${encodeURIComponent(status)}&limit=40`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.pendingItems = data.items || [];

      // Update badge counts
      const count = state.pendingItems.length;
      if (badge) {
        badge.textContent = count;
        badge.style.display = count > 0 ? 'inline-block' : 'none';
      }
      if (drawerBadge) {
        drawerBadge.textContent = count;
        drawerBadge.style.display = count > 0 ? 'inline-block' : 'none';
      }

      renderReviewGrid(state.pendingItems, container, status);
    } catch (err) {
      container.innerHTML = `<div class="error-state">Error loading review queue: ${escapeHtml(err.message)}</div>`;
    }
  }

  function renderReviewGrid(items, container, status) {
    if (!items || items.length === 0) {
      container.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1; padding: 48px 16px;">
          <div style="font-size: 2.2rem; margin-bottom: 8px;">🎉</div>
          <h4>All Caught Up!</h4>
          <p style="color: var(--text-muted); font-size: 0.85rem;">No ${escapeHtml(status)} embedding candidates requiring operator validation.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = items.map(item => {
      const thumbUrl = item.crop_path ? `/crops/${item.crop_path.split(/[\\/]/).pop()}` : '/static/avatar-placeholder.png';
      const confPct = Math.round((item.confidence || 0) * 100);
      const isPending = status === 'pending';

      const candidateName = item.candidate_entity_name || 'Unidentified Person';
      const candidateCat = item.candidate_category || 'person';

      let actionsHtml = '';
      if (isPending) {
        actionsHtml = `
          <div class="review-actions">
            <button class="btn btn-xs btn-confirm" data-id="${item.id}" title="Confirm match and lock as ground truth anchor">
              ✓ Confirm Match
            </button>
            <button class="btn btn-xs btn-reassign" data-id="${item.id}" title="Reassign to a different enrolled identity">
              🔄 Reassign
            </button>
            <button class="btn btn-xs btn-enroll-new" data-id="${item.id}" title="Enroll this visual signature as a new identity">
              ✨ New Identity
            </button>
            <button class="btn btn-xs btn-dismiss" data-id="${item.id}" title="Dismiss candidate without modifying gallery">
              ✕ Dismiss
            </button>
          </div>
        `;
      } else {
        actionsHtml = `
          <div style="font-size: 11px; color: var(--text-muted); padding-top: 6px;">
            Status: <strong>${escapeHtml(item.status.toUpperCase())}</strong> • ${escapeHtml(item.notes || 'No operator notes')}
          </div>
        `;
      }

      return `
        <div class="review-card glass-panel" data-id="${item.id}">
          <div class="review-card-top">
            <img class="review-thumb" src="${thumbUrl}" alt="Crop" onerror="this.src='/static/avatar-placeholder.png'" />
            <div class="review-meta">
              <div class="review-title">
                ${escapeHtml(candidateName)}
                <span class="badge-category ${candidateCat}">${candidateCat}</span>
              </div>
              <div class="review-candidate-match">
                ${item.similarity_to_best ? `Similarity: <strong>${(item.similarity_to_best * 100).toFixed(1)}%</strong>` : 'Borderline Sighting'}
              </div>
              <div class="review-timestamp">
                📷 ${escapeHtml(item.camera_id)} • Track #${item.track_id} • ${new Date(item.timestamp * 1000).toLocaleTimeString()}
              </div>
              <div class="confidence-meter" style="margin-top: 4px;">
                <span>Score:</span>
                <div class="confidence-bar-track">
                  <div class="confidence-bar-fill" style="width: ${confPct}%;"></div>
                </div>
                <span>${confPct}%</span>
              </div>
            </div>
          </div>
          ${actionsHtml}
        </div>
      `;
    }).join('');

    // Attach Event Listeners
    container.querySelectorAll('.btn-confirm').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        await confirmReviewItem(id);
      });
    });

    container.querySelectorAll('.btn-reassign').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        openReassignModal(id);
      });
    });

    container.querySelectorAll('.btn-enroll-new').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        enrollNewFromReview(id);
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

  function enrollNewFromReview(itemId) {
    const modal = document.getElementById('modal-quick-enroll-entity');
    const inputId = document.getElementById('quick-enroll-item-id');
    const inputName = document.getElementById('quick-enroll-name-input');
    if (inputId) inputId.value = itemId;
    if (inputName) {
      inputName.value = '';
      setTimeout(() => inputName.focus(), 60);
    }
    if (modal) modal.style.display = 'flex';
  }

  function initQuickEnrollModal() {
    const modal = document.getElementById('modal-quick-enroll-entity');
    const form = document.getElementById('quick-enroll-form');
    const closeBtn = document.getElementById('modal-quick-enroll-close');
    const cancelBtn = document.getElementById('modal-quick-enroll-cancel');

    const closeModal = () => {
      if (modal) modal.style.display = 'none';
      if (form) form.reset();
    };

    closeBtn?.addEventListener('click', closeModal);
    cancelBtn?.addEventListener('click', closeModal);

    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const itemId = document.getElementById('quick-enroll-item-id')?.value;
        const name = (document.getElementById('quick-enroll-name-input')?.value || '').trim();
        const category = document.getElementById('quick-enroll-category-select')?.value || 'person';

        if (!name) {
          showToast('Validation Required', 'Please enter a name for the entity.', 'warning');
          return;
        }

        try {
          const res = await fetch(`/api/active-learning/${itemId}/enroll-new`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: name,
              category: category,
              security_role: 'resident',
              notes: 'Enrolled via Active Learning Review Queue',
            }),
          });
          if (!res.ok) throw new Error('Enroll new failed');
          const data = await res.json();
          closeModal();
          showToast('Entity Enrolled', `Registered "${name}" (ID #${data.entity_id}) with initial signature locked!`, 'success');
          loadReviewQueue(state.currentReviewStatus);
        } catch (err) {
          showToast('Enrollment Error', err.message, 'error');
        }
      });
    }
  }

  async function openReassignModal(itemId) {
    const modal = document.getElementById('modal-review-reassign');
    const select = document.getElementById('reassign-entity-select');
    const idInput = document.getElementById('reassign-item-id');

    if (!modal || !select || !idInput) return;

    idInput.value = itemId;
    modal.style.display = 'flex';

    try {
      const res = await fetch('/entities');
      const entities = await res.json();
      select.innerHTML = '<option value="">Select target entity...</option>' +
        entities.map(e => `<option value="${e.id}">${escapeHtml(e.name)} (${escapeHtml(e.category || 'person')})</option>`).join('');
    } catch (err) {
      select.innerHTML = '<option value="">Error loading entities</option>';
    }
  }

  function initReassignModal() {
    const modal = document.getElementById('modal-review-reassign');
    const form = document.getElementById('review-reassign-form');
    const closeBtn = document.getElementById('modal-reassign-close');
    const cancelBtn = document.getElementById('modal-reassign-cancel');

    if (closeBtn && modal) closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    if (cancelBtn && modal) cancelBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.style.display = 'none';
      });
    }

    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const itemId = document.getElementById('reassign-item-id').value;
        const targetEntityId = document.getElementById('reassign-entity-select').value;
        const notes = document.getElementById('reassign-notes-input').value;

        if (!targetEntityId) {
          showToast('Selection Required', 'Please select a target entity.', 'warning');
          return;
        }

        try {
          const res = await fetch(`/api/active-learning/${itemId}/reassign`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              target_entity_id: parseInt(targetEntityId, 10),
              notes: notes || 'Operator reassigned candidate crop',
            }),
          });
          if (!res.ok) throw new Error('Reassignment failed');
          modal.style.display = 'none';
          showToast('Reassignment Saved', 'Signature assigned as locked anchor to target entity.', 'success');
          loadReviewQueue(state.currentReviewStatus);
        } catch (err) {
          showToast('Reassignment Error', err.message, 'error');
        }
      });
    }
  }

  function checkAlertEvents(alerts) {
    if (!alerts || !Array.isArray(alerts)) return;
    alerts.forEach(a => {
      const alertId = `${a.timestamp}_${a.event_type}_${a.entity_id || 0}`;
      if (state.recentAlertsSeen.has(alertId)) return;
      state.recentAlertsSeen.add(alertId);

      const type = a.event_type || 'alert';
      if (type.includes('intrusion') || type.includes('restricted')) {
        showToast(
          'CRITICAL SECURITY ALERT',
          `Intrusion detected in zone: ${a.zone_id || 'Security Zone'}. Entity: ${a.entity_name || 'Unidentified'}`,
          'alert'
        );
      } else if (type.includes('capacity')) {
        showToast(
          'Zone Threshold Warning',
          `Occupancy exceeded limit in ${a.zone_id || 'zone'} (${a.metadata?.occupancy || ''} people).`,
          'warning'
        );
      }
    });

    if (state.recentAlertsSeen.size > 200) {
      state.recentAlertsSeen.clear();
    }
  }

  function init() {
    initQuickEnrollModal();
    initReassignModal();
    if (window.TrackerApp.Enrollment?.init) {
      window.TrackerApp.Enrollment.init();
    }

    // Filter pills
    document.querySelectorAll('.review-filter-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('.review-filter-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        const status = pill.getAttribute('data-status') || 'pending';
        loadReviewQueue(status);
      });
    });

    // Auto-load pending queue
    loadReviewQueue('pending');
  }

  window.ReviewAndRSAC = {
    init: init,
    loadReviewQueue: loadReviewQueue,
    openVersionsModal: (entId, entName) => window.TrackerApp.RSACVersions?.openModal(entId, entName),
    checkAlertEvents: checkAlertEvents,
    confirmItem: confirmReviewItem,
    dismissItem: dismissReviewItem,
  };

  document.addEventListener('DOMContentLoaded', init);
})();
