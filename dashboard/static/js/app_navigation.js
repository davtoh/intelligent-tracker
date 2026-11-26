/**
 * Intelligent Tracker - Unified App.navigate(tab, SourceRef) & Hash Query Router.
 * Routes cross-tab deep-links (#live?camera=..., #studio?camera=...&zone=...,
 * #analytics?camera=..., #videos?video=...&offset_sec=..., #timeline?source=...&from=...&to=...)
 * with full ADR-15 SourceRef serialization, ActiveSourceContext sync, and MediaEmptyState guards.
 */
(function () {
  'use strict';

  function parseHash(rawHash) {
    const cleaned = String(rawHash || '').replace(/^#/, '').trim();
    if (!cleaned) return { route: '', params: {} };
    const qIdx = cleaned.indexOf('?');
    const route = (qIdx >= 0 ? cleaned.slice(0, qIdx) : cleaned).trim().toLowerCase();
    const params = {};
    if (qIdx >= 0) {
      const qs = new URLSearchParams(cleaned.slice(qIdx + 1));
      qs.forEach((val, key) => { params[key] = val; });
    }
    return { route, params };
  }

  function parseBboxParam(raw) {
    if (Array.isArray(raw) && raw.length >= 4) {
      const nums = raw.slice(0, 4).map(Number);
      return nums.every(Number.isFinite) ? nums : null;
    }
    if (typeof raw === 'string' && raw.trim()) {
      try {
        const parsed = raw.trim().startsWith('[') ? JSON.parse(raw) : raw.split(',');
        return parseBboxParam(parsed);
      } catch (_) {
        return null;
      }
    }
    return null;
  }

  function buildHash(tabId, sourceRef = {}) {
    const base = '#' + String(tabId || 'tab-live').replace(/^tab-/, '');
    if (!sourceRef || typeof sourceRef !== 'object') return base;
    const qs = new URLSearchParams();
    if (sourceRef.kind) qs.set('kind', String(sourceRef.kind));
    const cam = sourceRef.cameraId || sourceRef.camera_id || sourceRef.camera || '';
    if (cam) qs.set('camera', String(cam));
    if (sourceRef.source) qs.set('source', String(sourceRef.source));
    const videoFn = sourceRef.videoFilename || sourceRef.video_filename || sourceRef.video || '';
    if (videoFn) qs.set('video', String(videoFn));
    const runId = sourceRef.runId || sourceRef.run_id || '';
    if (runId) qs.set('run_id', String(runId));
    const offsetSec = sourceRef.mediaOffsetSec ?? sourceRef.media_offset_sec ?? sourceRef.offset_sec;
    if (offsetSec !== undefined && offsetSec !== null && offsetSec !== '' && Number.isFinite(Number(offsetSec))) {
      qs.set('offset_sec', String(offsetSec));
    }
    if (sourceRef.ts !== undefined && sourceRef.ts !== null && sourceRef.ts !== '' && Number.isFinite(Number(sourceRef.ts))) {
      qs.set('ts', String(sourceRef.ts));
    }
    const trackId = sourceRef.trackId ?? sourceRef.track_id;
    if (trackId !== undefined && trackId !== null && trackId !== '' && Number.isFinite(Number(trackId))) {
      qs.set('track_id', String(trackId));
    }
    const entityId = sourceRef.entityId ?? sourceRef.entity_id ?? sourceRef.entity;
    if (entityId !== undefined && entityId !== null && entityId !== '') qs.set('entity', String(entityId));
    const zone = sourceRef.zoneId || sourceRef.zone_id || sourceRef.zone || '';
    if (zone) qs.set('zone', String(zone));
    const bbox = parseBboxParam(sourceRef.bbox);
    if (bbox) qs.set('bbox', bbox.join(','));
    const fromVal = sourceRef.from ?? sourceRef.startTime;
    const toVal = sourceRef.to ?? sourceRef.endTime;
    if (fromVal !== undefined && fromVal !== null && fromVal !== '') qs.set('from', String(fromVal));
    if (toVal !== undefined && toVal !== null && toVal !== '') qs.set('to', String(toVal));
    const str = qs.toString();
    return str ? `${base}?${str}` : base;
  }

  async function validateSourceAvailability(sourceRef) {
    if (!window.ActiveSourceContext?.fetchCatalog || !window.ActiveSourceContext?.checkAvailability) return null;
    const hasTarget = Boolean(
      sourceRef.cameraId || sourceRef.camera || sourceRef.videoFilename || sourceRef.video || sourceRef.source
    );
    if (!hasTarget) return null;
    const catalog = await window.ActiveSourceContext.fetchCatalog();
    return { catalog, avail: window.ActiveSourceContext.checkAvailability(sourceRef, catalog) };
  }

  function showUnavailableForTarget(imgEl, avail, fallbackTitle, fallbackSub) {
    if (!imgEl) return;
    if (window.ActiveSourceContext?.showUnavailable) {
      window.ActiveSourceContext.showUnavailable(imgEl, avail);
    } else if (window.MediaEmptyState?.showEmpty) {
      window.MediaEmptyState.showEmpty(imgEl, avail?.title || fallbackTitle, avail?.subtitle || fallbackSub);
    }
    window.showToast?.('Source Unavailable', avail?.subtitle || fallbackSub, 'warning');
  }

  async function applyLiveRoute(camId, sourceRef) {
    if (!camId) return false;
    const check = await validateSourceAvailability(sourceRef);
    if (check && !check.avail.available) {
      const liveImg = document.getElementById('live-stream-img');
      window.LivePlayer?.detachLiveStream?.(liveImg);
      const titleEl = document.getElementById('video-stream-title');
      if (titleEl) titleEl.textContent = `Camera Unavailable: ${camId}`;
      showUnavailableForTarget(liveImg, check.avail, 'Camera Unavailable', `Camera '${camId}' does not exist.`);
      return false;
    }
    const liveImg = document.getElementById('live-stream-img');
    if (liveImg) window.MediaEmptyState?.hideEmpty?.(liveImg, 'block');
    window.App?.switchCamera?.(camId);
    return true;
  }

  async function applyStudioRoute(camId, videoFn, zoneId, sourceRef) {
    await window.Studio?.loadStudioChannels?.();
    const sel = document.getElementById('studio-camera-select');
    const targetVal = videoFn || camId || '';
    const check = await validateSourceAvailability(sourceRef);
    if (check && !check.avail.available) {
      showUnavailableForTarget(
        document.getElementById('studio-live-img'),
        check.avail,
        'Studio Source Unavailable',
        `Channel '${targetVal}' does not exist.`
      );
      return false;
    }
    if (sel && targetVal) {
      sel.value = targetVal;
      if (typeof Event === 'function' && typeof sel.dispatchEvent === 'function') {
        sel.dispatchEvent(new Event('change'));
      }
    }
    if (zoneId) {
      window.Studio?.selectZoneById?.(zoneId);
      window.showToast?.('Scenario Studio', `Opened ${targetVal || 'studio'} for zone ${zoneId}`, 'info');
    }
    return true;
  }

  async function applyAnalyticsRoute(sourceRef) {
    await window.AnalyticsView?.initSourceSelect?.();
    const sel = document.getElementById('analytics-source-select');
    const desired = window.ActiveSourceContext?.toSelectValue?.(sourceRef) || sourceRef.cameraId || sourceRef.videoFilename || '';
    if (sel && desired) sel.value = desired;
    const check = await validateSourceAvailability(sourceRef);
    if (check && !check.avail.available) {
      showUnavailableForTarget(
        document.getElementById('static-heatmap-img'),
        check.avail,
        'Analytics Source Unavailable',
        `Source '${desired}' does not exist.`
      );
      return false;
    }
    window.AnalyticsView?.loadTrafficFlows?.();
    window.AnalyticsView?.loadHeatmapMetadata?.();
    window.LivePlayer?.attachHeatmapImage?.(document.getElementById('static-heatmap-img'));
    return true;
  }

  async function applyVideosRoute(videoFn, sourceRef) {
    await window.VideoScrubber?.loadVideosList?.();
    if (!videoFn) return true;
    const check = await validateSourceAvailability({ kind: 'video', videoFilename: videoFn });
    const player = document.getElementById('scrubber-video-player');
    if (check && !check.avail.available) {
      showUnavailableForTarget(player, check.avail, 'Recorded Video Unavailable', `Video '${videoFn}' does not exist.`);
      return false;
    }
    if (player) window.MediaEmptyState?.hideEmpty?.(player, 'block');
    const vid = check?.avail?.item;
    window.VideoScrubber?.loadVideoIntoPlayer?.(
      vid?.video_url || `/videos/${encodeURIComponent(videoFn)}`,
      videoFn,
      vid?.web_compatible ?? true,
      vid?.codec || 'h264'
    );
    if (sourceRef.runId) window.VideoScrubber?.loadDetections?.(videoFn, sourceRef.runId);
    const offsetSec = sourceRef.mediaOffsetSec ?? sourceRef.media_offset_sec;
    if (offsetSec !== undefined && offsetSec !== null && Number.isFinite(Number(offsetSec))) {
      window.dispatchEvent?.(new CustomEvent('video-seek-request', {
        detail: { filename: videoFn, offsetSec: Math.max(0, Number(offsetSec)) },
      }));
    }
    return true;
  }

  async function applySourceRef(tabId, sourceRef = {}) {
    const camId = sourceRef.cameraId || sourceRef.camera_id || sourceRef.camera || '';
    const videoFn = sourceRef.videoFilename || sourceRef.video_filename || sourceRef.video || '';
    const zoneId = sourceRef.zoneId || sourceRef.zone_id || sourceRef.zone || '';
    if (camId || videoFn || sourceRef.source) {
      window.ActiveSourceContext?.set?.(sourceRef, { silent: true });
    }
    if (tabId === 'tab-live') return applyLiveRoute(camId, sourceRef);
    if (tabId === 'tab-studio') return applyStudioRoute(camId, videoFn, zoneId, sourceRef);
    if (tabId === 'tab-analytics') return applyAnalyticsRoute(sourceRef);
    if (tabId === 'tab-videos') return applyVideosRoute(videoFn || (!camId ? sourceRef.source || '' : ''), sourceRef);
    if (tabId === 'tab-timeline') {
      await window.GalleryTimeline?.loadTimelineFilters?.();
      await window.TimelineView?.applyFilter?.({
        entityId: sourceRef.entityId ?? sourceRef.entity ?? '',
        zoneId,
        source: sourceRef.source || camId || '',
        videoFilename: videoFn,
        runId: sourceRef.runId || sourceRef.run_id || '',
        startTime: sourceRef.startTime ?? sourceRef.from ?? '',
        endTime: sourceRef.endTime ?? sourceRef.to ?? '',
        offset: sourceRef.offset ?? 0,
      });
      return true;
    }
    if (tabId === 'tab-alerts') {
      await window.AlertsView?.loadAlerts?.({
        offset: sourceRef.offset ?? 0,
        filters: {
          camera_id: camId || sourceRef.source || '',
          zone_id: zoneId,
          start_time: sourceRef.startTime ?? sourceRef.from ?? '',
          end_time: sourceRef.endTime ?? sourceRef.to ?? '',
        },
      });
      return true;
    }
    return false;
  }

  async function navigate(tab, sourceRef = {}, opts = {}) {
    const raw = String(tab || 'tab-live').trim();
    const tabId = raw.startsWith('tab-') ? raw : `tab-${raw}`;
    const updateHash = opts.updateHash !== false;
    const hasRef = Boolean(sourceRef && Object.keys(sourceRef).length > 0);
    window.switchTab?.(tabId, false, { skipTimelineAutoLoad: tabId === 'tab-timeline' && hasRef });
    if (updateHash) {
      const nextHash = buildHash(tabId, sourceRef);
      if (window.location.hash !== nextHash) {
        window.history?.pushState?.(null, '', nextHash);
      }
    }
    if (hasRef) await applySourceRef(tabId, sourceRef);
    return tabId;
  }

  function paramsToSourceRef(p = {}) {
    const ref = {};
    if (p.kind) ref.kind = p.kind;
    if (p.camera || p.camera_id) ref.cameraId = p.camera || p.camera_id;
    if (p.source) ref.source = p.source;
    if (p.video || p.video_filename) ref.videoFilename = p.video || p.video_filename;
    if (p.run_id || p.runId) ref.runId = p.run_id || p.runId;
    const rawOffset = p.offset_sec ?? p.media_offset_sec ?? p.mediaOffsetSec;
    if (rawOffset !== undefined && rawOffset !== '' && Number.isFinite(Number(rawOffset))) {
      ref.mediaOffsetSec = Number(rawOffset);
    }
    if (p.ts !== undefined && p.ts !== '' && Number.isFinite(Number(p.ts))) ref.ts = Number(p.ts);
    const rawTrack = p.track_id ?? p.trackId;
    if (rawTrack !== undefined && rawTrack !== '' && Number.isFinite(Number(rawTrack))) ref.trackId = Number(rawTrack);
    if (p.entity || p.entity_id) ref.entityId = p.entity || p.entity_id;
    if (p.zone || p.zone_id) ref.zoneId = p.zone || p.zone_id;
    const bbox = parseBboxParam(p.bbox);
    if (bbox) ref.bbox = bbox;
    if (p.from !== undefined) ref.from = p.from;
    if (p.to !== undefined) ref.to = p.to;
    return ref;
  }

  window.AppNavigation = { parseHash, buildHash, paramsToSourceRef, applySourceRef, navigate };
})();
