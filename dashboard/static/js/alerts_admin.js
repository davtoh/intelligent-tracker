/**
 * Intelligent Tracker - Security Alerts Admin Lifecycle, Facets, Export & Deep-Links.
 * Keeps alerts_view.js under 330L by isolating /api/events/* admin actions.
 */
(function () {
  'use strict';

  const state = {
    facetsLoaded: false,
    activeSnapshotSrc: '',
    activeSnapshotName: 'alert_snapshot.jpg',
  };

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function populateSelectOptions(selectEl, values, defaultLabel) {
    if (!selectEl) return;
    const prev = selectEl.value || '';
    const items = Array.isArray(values) ? values : [];
    const opts = [`<option value="">${escapeHtml(defaultLabel)}</option>`];
    items.forEach((v) => {
      const val = String(v || '').trim();
      if (val) opts.push(`<option value="${escapeHtml(val)}">${escapeHtml(val)}</option>`);
    });
    selectEl.innerHTML = opts.join('');
    if (prev && items.includes(prev)) selectEl.value = prev;
  }

  function normalizeZoneName(raw) {
    const text = String(raw || '').trim();
    if (!text) return '';
    const idx = text.indexOf(':zone:');
    return idx >= 0 ? text.slice(idx + 6).trim() : text;
  }

  function populateDatalist(listEl, values, normalizer = null) {
    if (!listEl) return;
    const items = Array.isArray(values) ? values : [];
    const seen = new Set();
    const unique = [];
    items.forEach((v) => {
      const val = normalizer ? normalizer(v) : String(v || '').trim();
      const key = val.toLowerCase();
      if (val && !seen.has(key)) {
        seen.add(key);
        unique.push(val);
      }
    });
    listEl.innerHTML = unique.map((v) => `<option value="${escapeHtml(v)}"></option>`).join('');
  }

  async function loadFacets(force = false) {
    if (state.facetsLoaded && !force) return null;
    try {
      const res = await fetch('/api/events/facets');
      if (!res.ok) return null;
      const facets = await res.json();
      populateSelectOptions(document.getElementById('alerts-filter-camera'), facets?.cameras, 'All Cameras');
      populateDatalist(document.getElementById('alerts-type-options'), facets?.event_types);
      populateDatalist(document.getElementById('alerts-zone-options'), facets?.zones, normalizeZoneName);
      state.facetsLoaded = true;
      return facets;
    } catch (err) {
      console.debug('[AlertsAdmin] Failed to load facets:', err);
      return null;
    }
  }

  function syncBadgeFromResponse(data) {
    if (typeof data?.unread_alert_count === 'number') {
      window.AppUIHelpers?.syncAlertBadges?.(data.unread_alert_count);
    }
  }

  async function acknowledgeEvents({ eventIds = null, markAll = false, isRead = true } = {}) {
    const body = { mark_all: Boolean(markAll), is_read: Boolean(isRead) };
    if (Array.isArray(eventIds) && eventIds.length > 0) body.event_ids = eventIds;
    const res = await fetch('/api/events/acknowledge', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    syncBadgeFromResponse(data);
    await window.AlertsView?.loadAlerts?.();
    return data;
  }

  async function deleteEvent(eventId) {
    if (eventId === null || eventId === undefined || eventId === '') return null;
    const res = await fetch(`/api/events/${encodeURIComponent(String(eventId))}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    syncBadgeFromResponse(data);
    await window.AlertsView?.loadAlerts?.();
    return data;
  }

  async function clearMatchingEvents(filters = {}) {
    const payload = {};
    if (filters.camera_id) payload.camera_id = filters.camera_id;
    if (filters.severity) payload.severity = filters.severity;
    if (filters.event_type) payload.event_type = filters.event_type;
    if (filters.zone_id) payload.zone_id = filters.zone_id;
    const res = await fetch('/api/events/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    syncBadgeFromResponse(data);
    window.showToast?.('Alerts Cleared', `Removed ${data.deleted ?? 0} matching events`, 'info');
    await window.AlertsView?.loadAlerts?.({ offset: 0 });
    return data;
  }

  function buildExportUrl(format = 'csv', filters = {}) {
    const params = new URLSearchParams({ format: String(format || 'csv').toLowerCase() });
    if (filters.camera_id) params.set('camera_id', filters.camera_id);
    if (filters.severity) params.set('severity', filters.severity);
    if (filters.min_severity) params.set('min_severity', filters.min_severity);
    if (filters.event_type) params.set('event_type', filters.event_type);
    if (filters.zone_id) params.set('zone_id', filters.zone_id);
    if (filters.start_time !== undefined && filters.start_time !== '') params.set('start_time', String(filters.start_time));
    if (filters.end_time !== undefined && filters.end_time !== '') params.set('end_time', String(filters.end_time));
    return `/api/events/export?${params.toString()}`;
  }

  function triggerDownload(url, filename) {
    const a = document.createElement?.('a');
    if (a && typeof a.click === 'function') {
      a.href = url;
      if (filename) a.download = filename;
      a.style.display = 'none';
      document.body?.appendChild?.(a);
      a.click();
      a.remove?.();
      return true;
    }
    if (typeof window.open === 'function') {
      window.open(url, '_blank');
      return true;
    }
    return false;
  }

  function exportEvents(format = 'csv', filters = {}) {
    const fmt = String(format || 'csv').toLowerCase() === 'json' ? 'json' : 'csv';
    const url = buildExportUrl(fmt, filters);
    triggerDownload(url, `events_export.${fmt}`);
    return url;
  }

  function syncSnapshotDownloadButton(src, ev = {}) {
    state.activeSnapshotSrc = src || '';
    const cam = String(ev.camera_id || 'alert').replace(/[^a-zA-Z0-9_-]/g, '_');
    const eid = ev.id !== undefined && ev.id !== null ? `_${ev.id}` : '';
    state.activeSnapshotName = `${cam}${eid}_snapshot.jpg`;
    const btn = document.getElementById('btn-snapshot-download');
    if (btn) btn.disabled = !state.activeSnapshotSrc;
  }

  function downloadActiveSnapshot() {
    if (!state.activeSnapshotSrc) return false;
    return triggerDownload(state.activeSnapshotSrc, state.activeSnapshotName);
  }

  function jumpToLiveMonitor(cameraId) {
    if (!cameraId) return false;
    if (window.App?.navigate) {
      window.App.navigate('tab-live', { cameraId });
      return true;
    }
    window.switchTab?.('tab-live');
    window.App?.switchCamera?.(cameraId);
    return true;
  }

  async function jumpToScenarioStudio(cameraId, zoneId = '') {
    if (window.App?.navigate) {
      await window.App.navigate('tab-studio', { cameraId, zoneId });
      return true;
    }
    window.switchTab?.('tab-studio');
    await window.Studio?.loadStudioChannels?.();
    const sel = document.getElementById('studio-camera-select');
    if (sel && cameraId) {
      sel.value = cameraId;
      if (typeof Event === 'function' && typeof sel.dispatchEvent === 'function') {
        sel.dispatchEvent(new Event('change'));
      }
    }
    if (zoneId) {
      window.showToast?.('Scenario Studio', `Opened ${cameraId || 'studio'} for zone ${zoneId}`, 'info');
    }
    return true;
  }

  function buildSourceLinkHtml(ev) {
    const cam = ev.camera_id || '';
    const zone = ev.zone_id || '';
    const label = escapeHtml(zone || cam || 'System');
    const btns = [];
    if (cam) {
      btns.push(
        `<button type="button" class="btn btn-xs btn-outline btn-alert-live" data-camera-id="${escapeHtml(cam)}" onclick="window.AlertsAdmin?.jumpToLiveMonitor?.(this.getAttribute('data-camera-id'))" title="Open ${escapeHtml(cam)} in Live Monitor">📡 Live</button>`
      );
    }
    if (cam || zone) {
      btns.push(
        `<button type="button" class="btn btn-xs btn-outline btn-alert-studio" data-camera-id="${escapeHtml(cam)}" data-zone-id="${escapeHtml(zone)}" onclick="window.AlertsAdmin?.jumpToScenarioStudio?.(this.getAttribute('data-camera-id'), this.getAttribute('data-zone-id'))" title="Inspect in Scenario Studio">📐 Studio</button>`
      );
    }
    return `<div class="alert-source-links"><span>${label}</span>${btns.join('')}</div>`;
  }

  function buildActionButtonsHtml(ev) {
    if (ev.id === undefined || ev.id === null) return '<span class="text-subtle">--</span>';
    const nextRead = !ev.is_read;
    const ackLabel = ev.is_read ? 'Mark Unread' : 'Mark Seen';
    const ackVariant = ev.is_read ? 'outline' : 'primary';
    return `<div class="alert-action-group">
      <button type="button" class="btn btn-xs btn-${ackVariant} btn-alert-ack" data-event-id="${escapeHtml(ev.id)}" data-next-read="${nextRead ? '1' : '0'}" onclick="window.AlertsAdmin?.acknowledgeEvents?.({ eventIds: [${Number(ev.id)}], isRead: ${nextRead} })">${ackLabel}</button>
      <button type="button" class="btn btn-xs btn-outline btn-alert-delete" data-event-id="${escapeHtml(ev.id)}" onclick="window.AlertsAdmin?.deleteEvent?.(${Number(ev.id)})">🗑</button>
    </div>`;
  }

  function bindAdminControls(getFiltersFn) {
    const getFilters = typeof getFiltersFn === 'function' ? getFiltersFn : () => ({});
    const bindOnce = (id, fn) => {
      const el = document.getElementById(id);
      if (el && !el.dataset?.bound) {
        if (el.dataset) el.dataset.bound = '1';
        el.addEventListener?.('click', fn);
      }
    };
    bindOnce('btn-alerts-mark-all-read', () => acknowledgeEvents({ markAll: true, isRead: true }));
    bindOnce('btn-alerts-bulk-clear', () => clearMatchingEvents(getFilters()));
    bindOnce('btn-alerts-export-csv', () => exportEvents('csv', getFilters()));
    bindOnce('btn-alerts-export-json', () => exportEvents('json', getFilters()));
    bindOnce('btn-snapshot-download', () => downloadActiveSnapshot());
  }

  window.AlertsAdmin = {
    state,
    loadFacets,
    acknowledgeEvents,
    deleteEvent,
    clearMatchingEvents,
    buildExportUrl,
    exportEvents,
    syncSnapshotDownloadButton,
    downloadActiveSnapshot,
    jumpToLiveMonitor,
    jumpToScenarioStudio,
    buildSourceLinkHtml,
    buildActionButtonsHtml,
    bindAdminControls,
  };
})();
