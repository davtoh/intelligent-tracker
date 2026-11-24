/**
 * Two-State #modal-tag-entity Controller.
 * State A (Known Match): pre-fills entity, shows "✅ Confirm Match" and "🚫 Not <Name> / False Positive".
 * State B (New Subject): shows "💾 Enroll to Gallery" and hides "Not This" button.
 */
(function () {
  'use strict';

  const el = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null);

  function syncFromDom() {
    const entityId = (el('tag-entity-id')?.value || '').trim();
    const name = (el('tag-name-input')?.value || '').trim();
    const submitBtn = el('modal-tag-submit');
    const discourageBtn = el('btn-tag-discourage');
    const isKnown = Boolean(entityId);

    if (submitBtn) {
      submitBtn.textContent = isKnown ? '✅ Confirm Match' : '💾 Enroll to Gallery';
    }
    if (discourageBtn) {
      if (isKnown) {
        discourageBtn.style.display = 'inline-flex';
        discourageBtn.textContent = `🚫 Not ${name || 'This'} / False Positive`;
      } else {
        discourageBtn.style.display = 'none';
        discourageBtn.textContent = '🚫 Not This / False Positive';
      }
    }
    return isKnown ? 'known' : 'new';
  }

  function onCandidateSuppressed(entityId) {
    const eidInput = el('tag-entity-id');
    if (eidInput && String(eidInput.value || '') === String(entityId ?? '')) {
      eidInput.value = '';
    }
    return syncFromDom();
  }

  window.TagModalState = {
    syncFromDom,
    onCandidateSuppressed,
  };
})();
