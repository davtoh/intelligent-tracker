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
    const entities = Array.isArray(report.entities) ? report.entities : [];
    for (const ent of entities) {
      const label = ent?.entity?.name || ent?.entity_name || (ent?.entity?.id ? `Entity #${ent.entity.id}` : 'Entity');
      const directOffset = ent?.first_seen_sec ?? ent?.media_offset_sec ?? ent?.offset_sec;
      if (directOffset !== undefined && directOffset !== null && Number.isFinite(Number(directOffset))) {
        events.push({ offset_sec: Number(directOffset), kind: 'sighting', label });
        continue;
      }
      const timeline = Array.isArray(ent?.timeline) ? ent.timeline : [];
      for (const item of timeline) {
        const itemOffset = item?.media_offset_sec ?? item?.offset_sec;
        if (itemOffset !== undefined && itemOffset !== null && Number.isFinite(Number(itemOffset))) {
          events.push({ offset_sec: Number(itemOffset), kind: 'sighting', label });
        }
      }
    }
    const alerts = Array.isArray(report.alerts) ? report.alerts : [];
    for (const al of alerts) {
      const t = al?.media_offset_sec ?? al?.offset_sec;
      if (t !== undefined && t !== null && Number.isFinite(Number(t))) {
        events.push({ offset_sec: Number(t), kind: 'alert', label: al.event_type || al.message || 'RSAC Alert' });
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

  function normalizeJumpRef(raw = {}) {
    if (!raw || typeof raw !== 'object') return {};
    const out = {};
    const camId = raw.cameraId || raw.camera_id || raw.camera || '';
    const videoFn = raw.videoFilename || raw.video_filename || raw.video || '';
    if (camId) out.cameraId = String(camId);
    if (videoFn) out.videoFilename = String(videoFn);
    if (raw.kind) out.kind = String(raw.kind);
    else if (videoFn) out.kind = 'video';
    else if (camId) out.kind = 'camera';
    const runId = raw.runId || raw.run_id || '';
    if (runId) out.runId = String(runId);
    const off = raw.mediaOffsetSec ?? raw.media_offset_sec ?? raw.offset_sec;
    if (off !== undefined && off !== null && off !== '' && Number.isFinite(Number(off))) out.mediaOffsetSec = Number(off);
    const zoneId = raw.zoneId || raw.zone_id || raw.zone || '';
    if (zoneId) out.zoneId = String(zoneId);
    const trackId = raw.trackId ?? raw.track_id;
    if (trackId !== undefined && trackId !== null && trackId !== '' && Number.isFinite(Number(trackId))) out.trackId = Number(trackId);
    const entityId = raw.entityId ?? raw.entity_id ?? raw.entity;
    if (entityId !== undefined && entityId !== null && entityId !== '') out.entityId = entityId;
    if (raw.ts !== undefined && raw.ts !== null && Number.isFinite(Number(raw.ts))) out.ts = Number(raw.ts);
    return out;
  }

  function buildSourceJumpButtonsHtml(rawRef, opts = {}) {
    const ref = normalizeJumpRef(rawRef);
    const encoded = escapeHtml(JSON.stringify(ref));
    const parts = [];
    if (ref.cameraId) {
      parts.push(`<button type="button" class="btn btn-xs btn-outline btn-jump-live" data-jump-tab="tab-live" data-source-ref="${encoded}" title="Open in Live Monitor">📺 Live</button>`);
      parts.push(`<button type="button" class="btn btn-xs btn-outline btn-jump-studio" data-jump-tab="tab-studio" data-source-ref="${encoded}" title="Open in Scenario Studio">🎨 Studio</button>`);
    }
    if (ref.videoFilename && opts.includeVideo !== false) {
      parts.push(`<button type="button" class="btn btn-xs btn-outline btn-jump-video" data-jump-tab="tab-videos" data-source-ref="${encoded}" title="Seek in Video Studio">📼 Video</button>`);
    }
    return parts.join(' ');
  }

  function handleSourceJumpClick(targetOrBtn) {
    const el = targetOrBtn?.target ? targetOrBtn.target : targetOrBtn;
    const btn = el?.closest ? el.closest('[data-jump-tab][data-source-ref]') : (el?.getAttribute?.('data-jump-tab') ? el : null);
    if (!btn) return false;
    const tab = btn.getAttribute('data-jump-tab') || '';
    const raw = btn.getAttribute('data-source-ref') || '{}';
    let ref = {};
    try { ref = JSON.parse(raw); } catch (_) { ref = {}; }
    if (!tab) return false;
    const nav = window.App?.navigate || window.AppNavigation?.navigate;
    if (typeof nav === 'function') {
      nav(tab, ref);
      return true;
    }
    if (tab === 'tab-videos' && ref.videoFilename) {
      return seekToVideoTimestamp(ref.videoFilename, ref.mediaOffsetSec || 0);
    }
    return false;
  }

  if (typeof document !== 'undefined' && typeof document.addEventListener === 'function' && !document.__itSourceJumpBound) {
    document.__itSourceJumpBound = true;
    document.addEventListener('click', (e) => { handleSourceJumpClick(e); });
  }

  window.VideoTimelineLinks = {
    renderTimelineTicks,
    extractEventsFromReport,
    computeTickPercent,
    buildSeekInStudioButtonHtml,
    buildSourceJumpButtonsHtml,
    handleSourceJumpClick,
    seekToVideoTimestamp,
    seekFromButton,
  };
})();
