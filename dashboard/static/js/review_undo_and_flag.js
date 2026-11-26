/**
 * Intelligent Tracker - Reversible Review Undo Banner & Timeline Flag Controller.
 *
 * Manages:
 * - Session Undo banner (#review-undo-banner) & per-card Undo buttons on #tab-review
 * - Reason badges (Recurring Unknown / Timeline Flag) on review cards
 * - Delegated "🚩 Report wrong" flagging on #sightings-timeline-list cards
 */
(function () {
  'use strict';

  let lastDecision = null;
  const el = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null);

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderReasonBadgeHtml(item) {
    const reason = String(item?.reason || '').trim().toLowerCase();
    if (reason === 'recurring_unknown') {
      return '<span class="badge review-reason-badge reason-recurring-unknown" style="margin-left:6px;background:rgba(245,158,11,0.2);color:#fbbf24;border:1px solid rgba(245,158,11,0.45);">Recurring Unknown</span>';
    }
    if (reason === 'timeline_flag') {
      return '<span class="badge review-reason-badge reason-timeline-flag" style="margin-left:6px;background:rgba(239,68,68,0.2);color:#fca5a5;border:1px solid rgba(239,68,68,0.45);">Timeline Flag</span>';
    }
    if (reason === 'tag_correction') {
      return '<span class="badge review-reason-badge reason-tag-correction" style="margin-left:6px;background:rgba(6,182,212,0.2);color:#67e8f9;border:1px solid rgba(6,182,212,0.45);">Tag Correction</span>';
    }
    return '';
  }

  function renderCardUndoButtonHtml(item) {
    if (!item || item.status === 'pending') return '';
    return `<button type="button" class="btn btn-xs btn-outline btn-review-undo" data-review-id="${item.id}" title="Undo this review decision">↩ Undo</button>`;
  }

  function buildReportWrongButtonHtml(s) {
    if (!s) return '';
    const sid = s.id ?? '';
    const eid = s.entity_id ?? '';
    const cam = escapeHtml(s.camera_id || s.source || '');
    const vid = escapeHtml(s.video_filename || '');
    const off = Number(s.media_offset_sec || 0);
    const tid = s.track_id ?? 0;
    const run = escapeHtml(s.run_id || '');
    return `<button type="button" class="btn btn-xs btn-outline report-wrong-action" data-sighting-id="${sid}" data-entity-id="${eid}" data-camera-id="${cam}" data-video-filename="${vid}" data-media-offset="${off}" data-track-id="${tid}" data-run-id="${run}" title="Flag this sighting as a false positive for review">🚩 Report wrong</button>`;
  }

  function renderUndoBanner() {
    const banner = el('review-undo-banner');
    if (!banner) return;
    if (!lastDecision || (!lastDecision.decisionId && !lastDecision.reviewId)) {
      banner.style.display = 'none';
      banner.innerHTML = '';
      return;
    }
    const label = escapeHtml(lastDecision.label || 'Review action saved');
    banner.style.display = 'flex';
    banner.innerHTML = `
      <span class="review-undo-label">↩ ${label}</span>
      <div style="display:flex;gap:8px;align-items:center;">
        <button type="button" class="btn btn-xs btn-primary" id="btn-review-banner-undo">↩ Undo</button>
        <button type="button" class="btn btn-xs btn-outline" id="btn-review-banner-dismiss" aria-label="Dismiss undo banner">&times;</button>
      </div>
    `;
    el('btn-review-banner-undo')?.addEventListener('click', () => {
      undoDecision(lastDecision?.decisionId, lastDecision?.reviewId);
    });
    el('btn-review-banner-dismiss')?.addEventListener('click', () => {
      lastDecision = null;
      renderUndoBanner();
    });
  }

  function recordResolvedDecision(data) {
    if (!data || (!data.decision_id && !data.review_id)) return;
    const status = String(data.status || 'resolved');
    const target = data.entity_name || (data.entity_id ? `entity #${data.entity_id}` : 'candidate');
    lastDecision = {
      decisionId: data.decision_id ?? null,
      reviewId: data.review_id ?? null,
      label: `Decision (${status}) applied to ${target}`,
    };
    renderUndoBanner();
  }

  async function undoDecision(decisionId, reviewId) {
    const url = decisionId != null
      ? `/api/review/decisions/${encodeURIComponent(decisionId)}/undo`
      : (reviewId != null ? `/api/review/${encodeURIComponent(reviewId)}/undo` : '');
    if (!url) return null;
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer: 'operator' }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      lastDecision = null;
      renderUndoBanner();
      window.showToast?.('Decision Reverted', `Reverted ${data.action || 'review'} decision.`, 'info');
      window.loadGallery?.() || window.GalleryTimeline?.loadGallery?.();
      window.ReviewAndRSAC?.loadQueue?.('pending');
      return data;
    } catch (err) {
      window.showToast?.('Undo Failed', err.message || 'Undo failed', 'error');
      return null;
    }
  }

  function bindCardUndoButtons(container) {
    if (!container?.querySelectorAll) return;
    container.querySelectorAll('.btn-review-undo').forEach((btn) => {
      btn.addEventListener('click', () => {
        const rid = btn.getAttribute('data-review-id');
        if (rid) undoDecision(null, rid);
      });
    });
  }

  async function reportWrongFromButton(btn) {
    const numOrNull = (v) => (v !== null && v !== '' && Number.isFinite(Number(v)) ? Number(v) : null);
    const payload = {
      sighting_id: numOrNull(btn.getAttribute('data-sighting-id')),
      entity_id: numOrNull(btn.getAttribute('data-entity-id')),
      camera_id: btn.getAttribute('data-camera-id') || '',
      video_filename: btn.getAttribute('data-video-filename') || '',
      media_offset_sec: Number(btn.getAttribute('data-media-offset') || 0),
      track_id: Number(btn.getAttribute('data-track-id') || 0),
      run_id: btn.getAttribute('data-run-id') || '',
      notes: 'Flagged as wrong from #timeline',
    };
    try {
      const res = await fetch('/api/review/report-wrong', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      btn.disabled = true;
      btn.textContent = '🚩 Flagged';
      window.showToast?.('Sighting Flagged', 'Queued into Review & Learn inbox for correction.', 'info');
      window.ReviewAndRSAC?.loadQueue?.('pending');
      return data;
    } catch (err) {
      window.showToast?.('Flag Failed', err.message || 'Report wrong failed', 'error');
      return null;
    }
  }

  function initTimelineFlagDelegation() {
    const list = el('sightings-timeline-list');
    if (!list || list.dataset?.flagDelegated) return;
    if (list.dataset) list.dataset.flagDelegated = '1';
    const selector = '.report-wrong-action';
    list.addEventListener('click', (e) => {
      const btn = e.target?.closest ? e.target.closest(selector) : (e.target?.classList?.contains?.('report-wrong-action') ? e.target : null);
      if (btn) reportWrongFromButton(btn);
    });
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
      initTimelineFlagDelegation();
    });
  }

  window.ReviewUndoAndFlag = {
    renderReasonBadgeHtml,
    renderCardUndoButtonHtml,
    buildReportWrongButtonHtml,
    recordResolvedDecision,
    renderUndoBanner,
    undoDecision,
    bindCardUndoButtons,
    reportWrongFromButton,
    initTimelineFlagDelegation,
    getLastDecision: () => lastDecision,
  };
})();
