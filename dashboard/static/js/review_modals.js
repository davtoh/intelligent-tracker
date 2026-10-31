/**
 * Intelligent Tracker - Active Learning Review Modals Submodule.
 * Handles quick-enrollment and candidate signature reassign dialogs.
 */

(function () {
  'use strict';

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function showToast(title, body, type = 'info') {
    if (typeof window.showToast === 'function') {
      window.showToast(title, body, type);
    } else {
      alert(`${title}: ${body}`);
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

  function initQuickEnrollModal(onSuccess) {
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
          if (onSuccess) onSuccess();
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
        entities.map(ent => `<option value="${ent.id}">${escapeHtml(ent.name)} (${escapeHtml(ent.category || 'person')})</option>`).join('');
    } catch (err) {
      select.innerHTML = '<option value="">Error loading entities</option>';
    }
  }

  function initReassignModal(onSuccess) {
    const modal = document.getElementById('modal-review-reassign');
    const form = document.getElementById('review-reassign-form');
    const closeBtn = document.getElementById('modal-reassign-close');
    const cancelBtn = document.getElementById('modal-reassign-cancel');

    const closeModal = () => { if (modal) modal.style.display = 'none'; };
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
      });
    }

    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const itemId = document.getElementById('reassign-item-id')?.value;
        const targetEntityId = document.getElementById('reassign-entity-select')?.value;
        const notes = document.getElementById('reassign-notes-input')?.value;

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
          closeModal();
          showToast('Reassignment Saved', 'Signature assigned as locked anchor to target entity.', 'success');
          if (onSuccess) onSuccess();
        } catch (err) {
          showToast('Reassignment Error', err.message, 'error');
        }
      });
    }
  }

  window.ReviewModals = {
    openReassignModal: openReassignModal,
    initReassignModal: initReassignModal,
    enrollNewFromReview: enrollNewFromReview,
    initQuickEnrollModal: initQuickEnrollModal,
  };
})();

