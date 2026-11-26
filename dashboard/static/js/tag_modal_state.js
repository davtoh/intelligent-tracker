/**
 * Two-State + Correction Sub-Mode #modal-tag-entity Controller.
 * State A (Known Match): pre-fills entity, shows "✅ Confirm Match", "✏️ Correct...", and "🚫 Not <Name> / False Positive".
 * State A2 (Correcting): stores #tag-prior-entity-id, switches submit to "✏️ Save Correction", hides discourage/correct buttons.
 * State B (New Subject): shows "💾 Enroll to Gallery" and hides "Not This" / "Correct..." buttons.
 */
(function () {
  'use strict';

  const el = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null);

  function isCorrecting() {
    return Boolean((el('tag-prior-entity-id')?.value || '').trim());
  }

  function syncFromDom() {
    const entityId = (el('tag-entity-id')?.value || '').trim();
    const priorId = (el('tag-prior-entity-id')?.value || '').trim();
    const name = (el('tag-name-input')?.value || '').trim();
    const submitBtn = el('modal-tag-submit');
    const discourageBtn = el('btn-tag-discourage');
    const correctBtn = el('btn-tag-correct');
    const correcting = Boolean(priorId);
    const isKnown = Boolean(entityId) && !correcting;

    if (submitBtn) {
      submitBtn.textContent = correcting
        ? '✏️ Save Correction'
        : (isKnown ? '✅ Confirm Match' : '💾 Enroll to Gallery');
    }
    if (correctBtn) {
      correctBtn.style.display = isKnown ? 'inline-flex' : 'none';
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
    return correcting ? 'correcting' : (isKnown ? 'known' : 'new');
  }

  function enterCorrectionMode() {
    const eidInput = el('tag-entity-id');
    const priorInput = el('tag-prior-entity-id');
    const nameInput = el('tag-name-input');
    const currentId = (eidInput?.value || '').trim();
    if (!currentId || !priorInput) return syncFromDom();
    priorInput.value = currentId;
    if (eidInput) eidInput.value = '';
    if (nameInput) {
      nameInput.value = '';
      nameInput.focus?.();
    }
    return syncFromDom();
  }

  function exitCorrectionMode() {
    const priorInput = el('tag-prior-entity-id');
    if (priorInput) priorInput.value = '';
    return syncFromDom();
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
    enterCorrectionMode,
    exitCorrectionMode,
    isCorrecting,
    onCandidateSuppressed,
  };
})();
