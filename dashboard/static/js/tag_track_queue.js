/**
 * Intelligent Tracker - Multi-Box Overlap & Quick-Tag Queue Controller.
 * Manages #tag-track-picker-strip inside #modal-tag-entity so operators can
 * switch between overlapping tracks or batch-tag all active tracks in order.
 */
(function () {
  'use strict';

  const el = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null);

  let queueItems = [];
  let activeIndex = -1;
  let baseContext = {};
  let onSelectHandler = null;

  function trackKey(track, fallbackIdx) {
    const tid = track?.id ?? track?.track_id;
    const layer = track?._layerId || track?.run_id || '';
    if (tid != null && tid !== '') return `${layer}:${tid}`;
    if (Array.isArray(track?.bbox) && track.bbox.length >= 4) {
      return `${layer}:${track.bbox.map((v) => Math.round(Number(v) || 0)).join(',')}`;
    }
    return `idx:${fallbackIdx}`;
  }

  function formatChipLabel(item) {
    const trk = item.track || {};
    const tid = trk.id ?? trk.track_id;
    const prefix = item.done ? '✓ ' : '';
    if (trk.entity_name) {
      return `${prefix}${trk.entity_name}${tid != null ? ` (#${tid})` : ''}`;
    }
    const cls = trk.class_name || trk.label || trk.category || 'Track';
    return tid != null ? `${prefix}${cls} #${tid}` : `${prefix}${cls}`;
  }

  function getRemainingCount() {
    return queueItems.filter((item) => !item.done).length;
  }

  function renderStrip() {
    const strip = el('tag-track-picker-strip');
    if (!strip) return;
    if (queueItems.length <= 1) {
      strip.style.display = 'none';
      strip.innerHTML = '';
      return;
    }
    strip.style.display = 'flex';
    strip.innerHTML = '';

    const progress = document.createElement('div');
    progress.className = 'tag-queue-progress';
    const rem = getRemainingCount();
    const pos = activeIndex >= 0 ? activeIndex + 1 : 1;
    progress.textContent = `Track Queue: ${pos}/${queueItems.length} (${rem} remaining)`;
    strip.appendChild(progress);

    const chipsWrap = document.createElement('div');
    chipsWrap.className = 'tag-queue-chips';
    queueItems.forEach((item, idx) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tag-queue-chip';
      if (idx === activeIndex) btn.classList.add('active');
      if (item.done) btn.classList.add('done');
      btn.dataset.queueIndex = String(idx);
      btn.dataset.trackId = String(item.track?.id ?? item.track?.track_id ?? '');
      const label = formatChipLabel(item);
      btn.title = label;
      btn.textContent = label;
      btn.addEventListener('click', () => select(idx));
      chipsWrap.appendChild(btn);
    });
    strip.appendChild(chipsWrap);
  }

  function init(tracks, options = {}) {
    const seen = new Set();
    const deduped = [];
    (Array.isArray(tracks) ? tracks : []).forEach((trk, idx) => {
      if (!trk || typeof trk !== 'object') return;
      const key = trackKey(trk, idx);
      if (seen.has(key)) return;
      seen.add(key);
      deduped.push({ key, track: trk, done: false });
    });
    queueItems = deduped;
    baseContext = { ...(options.context || {}) };
    delete baseContext.queueTracks;
    delete baseContext.overlappingTracks;
    onSelectHandler = typeof options.onSelect === 'function' ? options.onSelect : null;

    if (queueItems.length === 0) {
      activeIndex = -1;
      renderStrip();
      return getState();
    }
    const activeKey = options.activeTrack ? trackKey(options.activeTrack, 0) : null;
    const foundIdx = activeKey ? queueItems.findIndex((it) => it.key === activeKey) : -1;
    activeIndex = foundIdx >= 0 ? foundIdx : 0;
    renderStrip();
    return getState();
  }

  function select(index) {
    if (!Number.isInteger(index) || index < 0 || index >= queueItems.length) return null;
    activeIndex = index;
    renderStrip();
    const item = queueItems[activeIndex];
    if (item && typeof onSelectHandler === 'function') {
      onSelectHandler(item.track, { ...baseContext });
    }
    return item ? item.track : null;
  }

  function findNextUntaggedIndex(startAfter) {
    for (let i = startAfter + 1; i < queueItems.length; i += 1) {
      if (!queueItems[i].done) return i;
    }
    for (let i = 0; i < startAfter; i += 1) {
      if (!queueItems[i].done) return i;
    }
    return -1;
  }

  function markCurrentDoneAndAdvance() {
    if (queueItems.length <= 1 || activeIndex < 0 || activeIndex >= queueItems.length) {
      clear();
      return { advanced: false, remaining: 0, track: null };
    }
    queueItems[activeIndex].done = true;
    const nextIdx = findNextUntaggedIndex(activeIndex);
    if (nextIdx === -1) {
      clear();
      return { advanced: false, remaining: 0, track: null };
    }
    const nextTrack = select(nextIdx);
    return { advanced: true, remaining: getRemainingCount(), track: nextTrack };
  }

  function clear() {
    queueItems = [];
    activeIndex = -1;
    baseContext = {};
    onSelectHandler = null;
    const strip = el('tag-track-picker-strip');
    if (strip) {
      strip.style.display = 'none';
      strip.innerHTML = '';
    }
  }

  function getState() {
    return {
      total: queueItems.length,
      activeIndex,
      remaining: getRemainingCount(),
      activeTrack: activeIndex >= 0 && activeIndex < queueItems.length ? queueItems[activeIndex].track : null,
      items: queueItems.map((it) => ({ key: it.key, done: it.done, track: it.track })),
    };
  }

  window.TagTrackQueue = {
    init,
    select,
    markCurrentDoneAndAdvance,
    clear,
    getState,
    hasActiveQueue: () => queueItems.length > 1,
  };
})();
