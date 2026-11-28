/**
 * Intelligent Tracker - Timeline Filter Reset & Active Window Chip Helpers.
 * Keeps gallery_timeline.js within modularity budgets while providing
 * active time-window badges and one-click filter/URL hash resets.
 */

(function () {
  'use strict';

  function formatBound(raw) {
    if (raw === undefined || raw === null || raw === '') return '';
    const text = String(raw).trim();
    if (!text) return '';
    if (!text.includes('-') && !text.includes(':')) {
      const num = Number(text);
      if (Number.isFinite(num) && num > 1e8) {
        return new Date(num * 1000).toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
      }
    }
    return text;
  }

  function formatWindowChipText({ startTime = '', endTime = '', videoFilename = '' } = {}) {
    const parts = [];
    const s = formatBound(startTime);
    const e = formatBound(endTime);
    if (s && e) parts.push(`🕒 ${s} → ${e}`);
    else if (s) parts.push(`🕒 From ${s}`);
    else if (e) parts.push(`🕒 Until ${e}`);
    if (videoFilename) parts.push(`🎬 ${videoFilename}`);
    return parts.join(' · ');
  }

  function syncActiveWindowChip(state = {}) {
    const chip = document.getElementById('timeline-active-window-chip');
    if (!chip) return '';
    const label = formatWindowChipText(state);
    chip.textContent = label;
    if (chip.style) chip.style.display = label ? 'inline-flex' : 'none';
    return label;
  }

  function clearTimelineUrlHash() {
    try {
      const hash = String(window.location?.hash || '');
      if (!hash.includes('?')) return;
      const baseHash = hash.split('?')[0] || '#tab-timeline';
      if (window.history?.replaceState) {
        const path = (window.location?.pathname || '') + (window.location?.search || '');
        window.history.replaceState(null, '', `${path}${baseHash}`);
      } else if (window.location) {
        window.location.hash = baseHash;
      }
    } catch (_) {
      // Ignore restricted history/location mutations in sandboxed test VMs.
    }
  }

  function resetTimelineInputs() {
    ['timeline-entity-select', 'timeline-zone-select', 'timeline-source-select'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    const limSel = document.getElementById('timeline-limit-select');
    if (limSel) limSel.value = '50';
  }

  window.TimelineFilterHelpers = {
    formatBound,
    formatWindowChipText,
    syncActiveWindowChip,
    clearTimelineUrlHash,
    resetTimelineInputs,
  };
})();
