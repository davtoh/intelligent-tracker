/**
 * Intelligent Tracker - Video Timeline Tick-Marks & Deep-Link Seeking.
 *
 * Renders color-coded sighting/alert tick-marks along #scrubber-timeline-slider
 * and provides 1-click "Seek in Studio" deep-link helpers across tabs.
 */

(function () {
  'use strict';

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatOffsetLabel(offsetSec) {
    const sec = Math.max(0, Number(offsetSec) || 0);
    const mins = Math.floor(sec / 60);
    const rem = Math.floor(sec % 60);
    return `${mins}:${rem < 10 ? '0' : ''}${rem}`;
  }

  function resolveTickType(ev) {
    const rawType = String(ev?.type || ev?.event_type || ev?.kind || 'sighting').toLowerCase();
    if (rawType.includes('alert') || rawType.includes('intrusion') || rawType.includes('restricted') || rawType.includes('rsac')) {
      return 'alert';
    }
    if (rawType.includes('review') || rawType.includes('triage')) {
      return 'review';
    }
    return 'sighting';
  }

  function computeTickPercent(offsetSec, durationSec) {
    if (!Number.isFinite(durationSec) || durationSec <= 0) return null;
    const clamped = Math.max(0, Math.min(durationSec, Number(offsetSec) || 0));
    return (clamped / durationSec) * 100;
  }

  function normalizeTimelineEvents(events, durationSec) {
    if (!Array.isArray(events) || !Number.isFinite(durationSec) || durationSec <= 0) return [];
    const seen = new Set();
    const normalized = [];
    for (const ev of events) {
      if (!ev || typeof ev !== 'object') continue;
      const offsetSec = Number(ev.offset_sec ?? ev.media_offset_sec ?? ev.time ?? 0);
      if (!Number.isFinite(offsetSec) || offsetSec < 0) continue;
      const kind = resolveTickType(ev);
      const bucket = `${kind}:${Math.round(offsetSec * 2)}`;
      if (seen.has(bucket)) continue;
      seen.add(bucket);
      const pct = computeTickPercent(offsetSec, durationSec);
      if (pct === null) continue;
      const label = ev.label || ev.entity_name || ev.event_type || (kind === 'alert' ? 'Alert' : 'Sighting');
      normalized.push({ offsetSec, pct, kind, label: String(label) });
    }
    return normalized;
  }

  function renderTimelineTicks(events, durationSec, containerEl = null) {
    const container = containerEl || document.getElementById('scrubber-timeline-ticks');
    if (!container) return [];
    const ticks = normalizeTimelineEvents(events, Number(durationSec));
    if (!ticks.length) {
      container.innerHTML = '';
      return [];
    }
    container.innerHTML = ticks.map((t) => {
      const title = `${t.label} @ ${formatOffsetLabel(t.offsetSec)}`;
      return `<button type="button" class="scrubber-tick scrubber-tick-${t.kind}" style="left: ${t.pct.toFixed(2)}%;" data-offset-sec="${t.offsetSec.toFixed(3)}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}"></button>`;
    }).join('');
    bindTickClickHandlers(container);
    return ticks;
  }

  function bindTickClickHandlers(container) {
    container.querySelectorAll('.scrubber-tick').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const offsetSec = Number(btn.getAttribute('data-offset-sec'));
        if (!Number.isFinite(offsetSec)) return;
        const player = document.getElementById('scrubber-video-player');
        if (player) {
          player.currentTime = Math.max(0, Math.min(player.duration || offsetSec, offsetSec));
          window.VideoScrubber?.renderOverlay?.();
        }
        window.dispatchEvent(new CustomEvent('video-tick-seek', { detail: { offsetSec } }));
      });
    });
  }

  function extractEventsFromReport(report) {
    if (!report || typeof report !== 'object') return [];
    const events = [];
    const occurrences = Array.isArray(report.occurrences) ? report.occurrences : [];
    for (const occ of occurrences) {
      const t = occ?.first_seen_sec ?? occ?.media_offset_sec ?? occ?.offset_sec;
      if (t !== undefined && t !== null) {
        events.push({ offset_sec: Number(t), kind: 'sighting', label: occ.entity_name || `Track #${occ.track_id ?? '?'}` });
      }
    }
    const alerts = Array.isArray(report.alerts) ? report.alerts : [];
    for (const al of alerts) {
      const t = al?.media_offset_sec ?? al?.offset_sec;
      if (t !== undefined && t !== null) {
        events.push({ offset_sec: Number(t), kind: 'alert', label: al.event_type || 'RSAC Alert' });
      }
    }
    return events;
  }

  function buildSeekInStudioButtonHtml(videoFilename, offsetSec = 0) {
    if (!videoFilename || typeof videoFilename !== 'string' || !videoFilename.trim()) return '';
    const safeFile = escapeHtml(videoFilename.trim());
    const safeOffset = Math.max(0, Number(offsetSec) || 0).toFixed(2);
    const title = `Jump to ${videoFilename.trim()} at ${formatOffsetLabel(safeOffset)}`;
    return `<button type="button" class="btn btn-xs btn-outline btn-seek-studio" data-video-filename="${safeFile}" data-offset-sec="${safeOffset}" onclick="window.VideoTimelineLinks?.seekFromButton?.(this)" title="${escapeHtml(title)}">📼 Seek in Studio</button>`;
  }

  function seekToVideoTimestamp(videoFilename, offsetSec = 0) {
    if (!videoFilename || typeof videoFilename !== 'string' || !videoFilename.trim()) return false;
    const cleanFilename = videoFilename.trim();
    const safeOffset = Math.max(0, Number(offsetSec) || 0);
    if (typeof window.switchTab === 'function') {
      window.switchTab('tab-videos');
    } else if (typeof window !== 'undefined' && window.location) {
      window.location.hash = '#videos';
    }
    window.dispatchEvent(new CustomEvent('video-seek-request', {
      detail: { filename: cleanFilename, offsetSec: safeOffset },
    }));
    return true;
  }

  function seekFromButton(btnEl) {
    if (!btnEl) return false;
    const fn = btnEl.getAttribute?.('data-video-filename') || btnEl.dataset?.videoFilename;
    const offset = btnEl.getAttribute?.('data-offset-sec') ?? btnEl.dataset?.offsetSec ?? 0;
    return seekToVideoTimestamp(fn, Number(offset) || 0);
  }

  window.VideoTimelineLinks = {
    renderTimelineTicks,
    extractEventsFromReport,
    computeTickPercent,
    buildSeekInStudioButtonHtml,
    seekToVideoTimestamp,
    seekFromButton,
  };
})();
