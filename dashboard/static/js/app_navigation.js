/**
 * Intelligent Tracker - Unified App.navigate(tab, SourceRef) & Hash Query Router.
 * Routes cross-tab deep-links (#live?camera=..., #studio?camera=...&zone=...,
 * #timeline?source=...&from=...&to=...) and awaits async filter/channel loaders.
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

  function buildHash(tabId, sourceRef = {}) {
    const base = '#' + String(tabId || 'tab-live').replace(/^tab-/, '');
    if (!sourceRef || typeof sourceRef !== 'object') return base;
    const qs = new URLSearchParams();
    const cam = sourceRef.cameraId || sourceRef.camera || '';
    if (cam) qs.set('camera', String(cam));
    if (sourceRef.source) qs.set('source', String(sourceRef.source));
    if (sourceRef.zoneId || sourceRef.zone) qs.set('zone', String(sourceRef.zoneId || sourceRef.zone));
    if (sourceRef.entityId) qs.set('entity', String(sourceRef.entityId));
    if (sourceRef.videoFilename) qs.set('video', String(sourceRef.videoFilename));
    const fromVal = sourceRef.from ?? sourceRef.startTime;
    const toVal = sourceRef.to ?? sourceRef.endTime;
    if (fromVal !== undefined && fromVal !== null && fromVal !== '') qs.set('from', String(fromVal));
    if (toVal !== undefined && toVal !== null && toVal !== '') qs.set('to', String(toVal));
    const str = qs.toString();
    return str ? `${base}?${str}` : base;
  }

  async function applySourceRef(tabId, sourceRef = {}) {
    const camId = sourceRef.cameraId || sourceRef.camera || '';
    const zoneId = sourceRef.zoneId || sourceRef.zone || '';
    if (tabId === 'tab-live' && camId) {
      window.App?.switchCamera?.(camId);
      return true;
    }
    if (tabId === 'tab-studio') {
      await window.Studio?.loadStudioChannels?.();
      const sel = document.getElementById('studio-camera-select');
      if (sel && camId) {
        sel.value = camId;
        if (typeof Event === 'function' && typeof sel.dispatchEvent === 'function') {
          sel.dispatchEvent(new Event('change'));
        }
      }
      if (zoneId) {
        window.Studio?.selectZoneById?.(zoneId);
        window.showToast?.('Scenario Studio', `Opened ${camId || 'studio'} for zone ${zoneId}`, 'info');
      }
      return true;
    }
    if (tabId === 'tab-timeline') {
      await window.GalleryTimeline?.loadTimelineFilters?.();
      await window.TimelineView?.applyFilter?.({
        entityId: sourceRef.entityId ?? sourceRef.entity ?? '',
        zoneId,
        source: sourceRef.source || camId || '',
        videoFilename: sourceRef.videoFilename || sourceRef.video || '',
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
    if (p.camera) ref.cameraId = p.camera;
    if (p.source) ref.source = p.source;
    if (p.zone) ref.zoneId = p.zone;
    if (p.entity) ref.entityId = p.entity;
    if (p.video) ref.videoFilename = p.video;
    if (p.from !== undefined) ref.from = p.from;
    if (p.to !== undefined) ref.to = p.to;
    return ref;
  }

  window.AppNavigation = { parseHash, buildHash, paramsToSourceRef, applySourceRef, navigate };
})();
