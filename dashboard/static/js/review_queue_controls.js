/**
 * Intelligent Tracker - Review Queue Triage Controls, Pagination & Deep-Link Highlight.
 * Manages filter/sort/offset state, bulk-dismiss actions, and card focus/highlight.
 */
(function () {
  'use strict';

  const state = {
    status: 'pending', matched: '', reason: '', sort: 'newest',
    offset: 0, limit: 50, total: 0, totalPending: 0,
  };

  function getState() { return { ...state }; }

  function setState(partial = {}) {
    if (partial.status !== undefined) state.status = String(partial.status || 'pending');
    if (partial.matched !== undefined) state.matched = String(partial.matched || '');
    if (partial.reason !== undefined) state.reason = String(partial.reason || '');
    if (partial.sort !== undefined) state.sort = String(partial.sort || 'newest');
    if (partial.offset !== undefined) state.offset = Math.max(0, Number(partial.offset) || 0);
    if (partial.limit !== undefined) state.limit = Math.max(1, Number(partial.limit) || 50);
    if (partial.total !== undefined) state.total = Math.max(0, Number(partial.total) || 0);
    if (partial.totalPending !== undefined) state.totalPending = Math.max(0, Number(partial.totalPending) || 0);
    return getState();
  }

  function syncFiltersFromDom() {
    const matchedEl = document.getElementById('review-filter-matched');
    const reasonEl = document.getElementById('review-filter-reason');
    const sortEl = document.getElementById('review-sort-select');
    if (matchedEl) state.matched = String(matchedEl.value || '');
    if (reasonEl) state.reason = String(reasonEl.value || '');
    if (sortEl) state.sort = String(sortEl.value || 'newest');
  }

  function buildQueryUrl(overrides = {}) {
    syncFiltersFromDom();
    const qs = new URLSearchParams();
    qs.set('status', String(overrides.status ?? state.status ?? 'pending'));
    qs.set('limit', String(overrides.limit ?? state.limit ?? 50));
    qs.set('offset', String(Math.max(0, Number(overrides.offset ?? state.offset ?? 0) || 0)));
    const matched = overrides.matched ?? state.matched ?? '';
    const reason = overrides.reason ?? state.reason ?? '';
    const sort = overrides.sort ?? state.sort ?? 'newest';
    if (matched) qs.set('matched', String(matched));
    if (reason) qs.set('reason', String(reason));
    if (sort && sort !== 'newest') qs.set('sort', String(sort));
    return `/api/review/queue?${qs.toString()}`;
  }

  function updatePagination(meta = {}) {
    const total = Math.max(0, Number(meta.total ?? state.total) || 0);
    const count = Math.max(0, Number(meta.count ?? 0) || 0);
    const offset = Math.max(0, Number(meta.offset ?? state.offset) || 0);
    const limit = Math.max(1, Number(meta.limit ?? state.limit) || 50);
    const status = String(meta.status ?? state.status ?? 'pending');
    Object.assign(state, { total, offset, limit, status });
    if (meta.totalPending !== undefined) state.totalPending = Math.max(0, Number(meta.totalPending) || 0);

    const bar = document.getElementById('review-pagination-bar');
    const info = document.getElementById('review-page-info');
    const prevBtn = document.getElementById('review-page-prev');
    const nextBtn = document.getElementById('review-page-next');
    const bulkBtn = document.getElementById('btn-review-bulk-dismiss');
    if (bar) bar.style.display = total > 0 ? 'flex' : 'none';
    if (info) {
      const start = count > 0 ? offset + 1 : 0;
      const end = count > 0 ? Math.min(total, offset + count) : 0;
      info.textContent = total > 0 ? `Showing ${start}–${end} of ${total}` : 'Showing 0 of 0';
    }
    if (prevBtn) prevBtn.disabled = offset <= 0;
    if (nextBtn) nextBtn.disabled = (offset + count) >= total;
    if (bulkBtn) {
      bulkBtn.disabled = !(status === 'pending' && total > 0);
      bulkBtn.style.display = status === 'pending' ? '' : 'none';
    }
  }

  async function bulkDismissFiltered(onReload, onToast) {
    syncFiltersFromDom();
    const label = state.matched === 'unmatched' ? 'unidentified pending' : 'matching pending';
    if (typeof window.confirm === 'function' && !window.confirm(`Dismiss all ${label} review candidates?`)) return null;
    try {
      const res = await fetch('/api/review/bulk-dismiss', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status: state.status || 'pending',
          matched: state.matched || null,
          reason: state.reason || null,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.offset = 0;
      onToast?.('Bulk Dismissed', `Dismissed ${data.dismissed ?? 0} candidate(s).`, 'info');
      await onReload?.();
      return data;
    } catch (err) {
      onToast?.('Bulk Dismiss Error', err.message, 'error');
      return null;
    }
  }

  function findCardById(container, reviewId) {
    if (!container) return null;
    const target = String(reviewId);
    const cards = container.querySelectorAll ? Array.from(container.querySelectorAll('.review-card')) : [];
    return cards.find((el) => String(el.getAttribute?.('data-item-id') ?? '') === target) || null;
  }

  async function highlightReviewItem(reviewId, opts = {}) {
    if (reviewId === undefined || reviewId === null || reviewId === '') return null;
    const container = opts.container || document.getElementById('review-queue-container');
    if (!container) return null;
    let card = findCardById(container, reviewId);
    if (!card && typeof opts.buildCardHtml === 'function') {
      try {
        const res = await (opts.fetchFn || fetch)(`/api/review/${encodeURIComponent(reviewId)}`);
        if (res && res.ok) {
          const html = opts.buildCardHtml(await res.json());
          if (typeof container.insertAdjacentHTML === 'function') {
            container.querySelector?.('.empty-state')?.remove?.();
            container.insertAdjacentHTML('afterbegin', html);
          } else {
            container.innerHTML = html + (container.innerHTML || '');
          }
          opts.bindCardButtons?.(container);
          card = findCardById(container, reviewId);
        }
      } catch (_) { card = null; }
    }
    const cards = container.querySelectorAll ? Array.from(container.querySelectorAll('.review-card')) : [];
    cards.forEach((el) => el.classList?.remove?.('review-card-highlight'));
    if (card) {
      card.classList?.add?.('review-card-highlight');
      card.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    }
    return card;
  }

  function bindControls(onReload, onToast) {
    ['review-filter-matched', 'review-filter-reason', 'review-sort-select'].forEach((id) => {
      document.getElementById(id)?.addEventListener('change', () => {
        state.offset = 0;
        syncFiltersFromDom();
        onReload?.();
      });
    });
    document.getElementById('review-page-prev')?.addEventListener('click', () => {
      if (state.offset <= 0) return;
      state.offset = Math.max(0, state.offset - state.limit);
      onReload?.();
    });
    document.getElementById('review-page-next')?.addEventListener('click', () => {
      if (state.offset + state.limit >= state.total) return;
      state.offset += state.limit;
      onReload?.();
    });
    document.getElementById('btn-review-bulk-dismiss')?.addEventListener('click', () => {
      bulkDismissFiltered(onReload, onToast);
    });
  }

  window.ReviewQueueControls = {
    getState, setState, syncFiltersFromDom, buildQueryUrl,
    updatePagination, bulkDismissFiltered, highlightReviewItem, bindControls,
  };
})();
