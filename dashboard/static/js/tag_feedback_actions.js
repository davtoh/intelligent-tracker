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

  async function submitDiscourage(payload) {
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
    window.InteractiveCanvas?.closeTagModal?.();
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

  async function discourageCandidate(cand, getActiveCameraId) {
    try {
      const payload = buildModalPayload(
        getActiveCameraId,
        cand?.entity_id ?? null,
        cand?.name || ''
      );
      return await submitDiscourage(payload);
    } catch (err) {
      window.showToast?.('Feedback Failed', err.message || 'Discourage failed', 'error');
      return null;
    }
  }

  function attachCandidateDiscourage(btn, cand, _box, getActiveCameraId) {
    if (!btn || typeof document === 'undefined') return;
    const xBtn = document.createElement('span');
    xBtn.className = 'candidate-discourage-btn';
    xBtn.setAttribute('role', 'button');
    xBtn.setAttribute('title', `Not ${cand?.name || 'this entity'}`);
    xBtn.textContent = ' ✕';
    xBtn.style.marginLeft = '6px';
    xBtn.style.color = '#f87171';
    xBtn.style.cursor = 'pointer';
    xBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      discourageCandidate(cand, getActiveCameraId);
    });
    btn.appendChild(xBtn);
  }

  window.TagFeedbackActions = {
    buildModalPayload,
    submitDiscourage,
    discourageFromModal,
    discourageCandidate,
    attachCandidateDiscourage,
    onTagCommitted,
  };
})();
