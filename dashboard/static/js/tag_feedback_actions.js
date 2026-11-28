/**
 * Intelligent Tracker - Supervised Re-ID Negative & Correction Actions.
 * Handles "Not This / False Positive" and per-candidate discourage requests
 * from #modal-tag-entity without expanding interactive_canvas.js.
 */
(function () {
  'use strict';

  const el = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null);

  function buildModalPayload(getActiveCameraId, overrideEntityId, overrideLabel) {
    const sourceType = el('tag-source-type')?.value || 'live';
    const cropBase64 = el('tag-crop-base64')?.value || null;
    const bboxVal = el('tag-bbox-val')?.value || '';
    const bbox = !cropBase64 && bboxVal ? JSON.parse(bboxVal) : null;
    const rawEid = overrideEntityId !== undefined ? overrideEntityId : el('tag-entity-id')?.value;
    const entityId = rawEid !== '' && rawEid != null ? parseInt(rawEid, 10) : null;
    const rawTid = el('tag-track-id')?.value;
    const trackId = rawTid !== '' && rawTid != null ? parseInt(rawTid, 10) : null;
    const tsVal = el('tag-timestamp-sec')?.value ?? '';
    const camId = typeof getActiveCameraId === 'function'
      ? getActiveCameraId()
      : (window.LivePlayer?.getActiveCameraId?.() || null);
    return {
      entity_id: Number.isFinite(entityId) ? entityId : null,
      label: String(overrideLabel !== undefined ? overrideLabel : (el('tag-name-input')?.value || '')).trim(),
      track_id: Number.isFinite(trackId) ? trackId : null,
      bbox,
      crop_base64: cropBase64,
      notes: (el('tag-notes-input')?.value || '').trim(),
      camera_id: sourceType === 'video' ? null : camId,
      video_filename: sourceType === 'video' ? ((el('tag-video-filename')?.value || '').trim() || null) : null,
      timestamp_sec: sourceType === 'video' && tsVal !== '' ? parseFloat(tsVal) : null,
    };
  }

  async function submitDiscourage(payload, opts = {}) {
    const res = await fetch('/api/tag/discourage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Discourage request failed');
    }
    const json = await res.json();
    if (!opts.keepModalOpen) {
      window.InteractiveCanvas?.closeTagModal?.();
    } else {
      opts.chipBtn?.remove?.();
      window.TagTrackQueue?.recordSuppressedEntity?.(payload.entity_id);
      window.TagModalState?.onCandidateSuppressed?.(payload.entity_id);
    }
    const msg = payload.entity_id
      ? `Recorded negative exemplar for entity #${payload.entity_id}.`
      : 'Recorded global false-positive exemplar.';
    window.showToast?.('Feedback Recorded', msg, 'info');
    onTagCommitted(payload, json);
    return json;
  }

  function onTagCommitted(payload, _res) {
    const fn = payload?.video_filename;
    if (fn) {
      window.VideoBatchReports?.invalidateCachedReports?.(fn);
      if (window.VideoBatchReports?.getCurrentFilename?.() === fn) {
        window.VideoBatchReports?.restoreReportForFile?.(fn);
      }
      window.OverlayLayers?.ensureLoaded?.(fn, { force: true });
    }
    window.loadGallery?.() || window.GalleryTimeline?.loadGallery?.();
    window.ReviewAndRSAC?.loadQueue?.();
  }

  async function discourageFromModal(getActiveCameraId) {
    try {
      const payload = buildModalPayload(getActiveCameraId);
      return await submitDiscourage(payload);
    } catch (err) {
      window.showToast?.('Feedback Failed', err.message || 'Discourage failed', 'error');
      return null;
    }
  }

  async function discourageCandidate(cand, getActiveCameraId, chipBtn) {
    try {
      const payload = buildModalPayload(
        getActiveCameraId,
        cand?.entity_id ?? null,
        cand?.name || ''
      );
      return await submitDiscourage(payload, { keepModalOpen: true, chipBtn });
    } catch (err) {
      window.showToast?.('Feedback Failed', err.message || 'Discourage failed', 'error');
      return null;
    }
  }

  function attachCandidateDiscourage(btn, cand, _box, getActiveCameraId) {
    if (!btn || typeof document === 'undefined') return;
    const xBtn = document.createElement('span');
    xBtn.className = ['candidate', 'discourage', 'btn'].join('-');
    xBtn.setAttribute('role', 'button');
    xBtn.setAttribute('title', `Not ${cand?.name || 'this entity'}`);
    xBtn.textContent = ' ✕';
    xBtn.style.marginLeft = '6px';
    xBtn.style.color = '#f87171';
    xBtn.style.cursor = 'pointer';
    xBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      discourageCandidate(cand, getActiveCameraId, btn);
    });
    btn.appendChild(xBtn);
  }

  async function submitCorrection(getActiveCameraId) {
    const priorRaw = (el('tag-prior-entity-id')?.value || '').trim();
    const name = (el('tag-name-input')?.value || '').trim();
    if (!priorRaw || !name) return null;
    const base = buildModalPayload(getActiveCameraId);
    const payload = {
      prior_entity_id: parseInt(priorRaw, 10),
      entity_name: name,
      category: el('tag-category-select')?.value || 'person',
      entity_id: base.entity_id,
      camera_id: base.camera_id,
      video_filename: base.video_filename,
      timestamp_sec: base.timestamp_sec,
      bbox: base.bbox,
      crop_base64: base.crop_base64,
      notes: base.notes,
      track_id: base.track_id,
    };
    const res = await fetch('/api/tag/correct', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Correction request failed');
    }
    const json = await res.json();
    window.TagModalState?.exitCorrectionMode?.();
    const adv = window.TagTrackQueue?.markCurrentDoneAndAdvance?.();
    if (!adv?.advanced) window.InteractiveCanvas?.closeTagModal?.();
    window.ReviewUndoAndFlag?.recordResolvedDecision?.(json);
    window.showToast?.('Identity Corrected', `Reassigned match to "${name}".`, 'success');
    onTagCommitted(payload, json);
    return json;
  }

  function initCorrectionControls(getActiveCameraId) {
    const correctBtn = el('btn-tag-correct');
    if (correctBtn && !correctBtn.dataset?.correctBound) {
      if (correctBtn.dataset) correctBtn.dataset.correctBound = '1';
      correctBtn.addEventListener('click', () => window.TagModalState?.enterCorrectionMode?.());
    }
    const form = el('tag-entity-form');
    if (form && !form.dataset?.correctSubmitBound) {
      if (form.dataset) form.dataset.correctSubmitBound = '1';
      form.addEventListener('submit', async (e) => {
        if (!window.TagModalState?.isCorrecting?.()) return;
        e.preventDefault();
        e.stopImmediatePropagation?.();
        try {
          await submitCorrection(getActiveCameraId);
        } catch (err) {
          window.showToast?.('Correction Failed', err.message || 'Correction failed', 'error');
        }
      }, true);
    }
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => initCorrectionControls());
  }

  window.TagFeedbackActions = {
    buildModalPayload,
    submitDiscourage,
    submitCorrection,
    discourageFromModal,
    discourageCandidate,
    attachCandidateDiscourage,
    initCorrectionControls,
    onTagCommitted,
  };
})();
