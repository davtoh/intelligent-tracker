/**
 * Intelligent Tracker - Security Alerts Filter, Pagination & Snapshot Canvas Preview.
 * Reuses UnifiedCanvasOverlay + OverlayControlBar inside #modal-snapshot-view.
 */
(function () {
  'use strict';

  const state = {
    offset: 0, limit: 50, total: 0, hasMore: false,
    eventsByIndex: [], selectedIds: new Set(), selectAllMatching: false,
    featureVisibility: { bboxes: true, track_ids: true, dwell_timers: true, velocity: false, zones: true, tripwires: true },
    activePreviewEvent: null,
  };

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function readFiltersFromDom() {
    const camEl = document.getElementById('alerts-filter-camera');
    const sevEl = document.getElementById('alerts-filter-severity');
    const minSevEl = document.getElementById('alerts-filter-min-severity');
    const typeEl = document.getElementById('alerts-filter-type');
    const zoneEl = document.getElementById('alerts-filter-zone');
    const cameraVal = camEl ? String(camEl.value ?? '').trim() : String(window.App?.getActiveCameraId?.() ?? '').trim();
    return {
      camera_id: cameraVal,
      severity: (sevEl?.value || '').trim(),
      min_severity: (minSevEl?.value || '').trim(),
      event_type: (typeEl?.value || '').trim(),
      zone_id: (zoneEl?.value || '').trim(),
    };
  }

  function buildEventsUrl(filters = readFiltersFromDom()) {
    const params = new URLSearchParams({
      paginated: 'true',
      limit: String(state.limit),
      offset: String(state.offset),
    });
    if (filters.camera_id) params.set('camera_id', filters.camera_id);
    if (filters.severity) params.set('severity', filters.severity);
    if (filters.min_severity) params.set('min_severity', filters.min_severity);
    if (filters.event_type) params.set('event_type', filters.event_type);
    if (filters.zone_id) params.set('zone_id', filters.zone_id);
    if (filters.start_time !== undefined && filters.start_time !== '') params.set('start_time', String(filters.start_time));
    if (filters.end_time !== undefined && filters.end_time !== '') params.set('end_time', String(filters.end_time));
    return `/events?${params.toString()}`;
  }

  function formatShortTime(ts) {
    const n = Number(ts);
    if (!Number.isFinite(n) || n <= 0) return '';
    return new Date(n * 1000).toLocaleTimeString([], { hour12: false });
  }

  function formatDwellWindow(ev) {
    const meta = ev?.metadata || {};
    const entry = ev?.entry_time ?? meta.entry_time;
    const exit = ev?.exit_time ?? meta.exit_time;
    const dwell = ev?.dwell_time ?? meta.dwell_time;
    const entryStr = formatShortTime(entry);
    const exitStr = formatShortTime(exit);
    const dwellStr = Number.isFinite(Number(dwell)) && dwell !== null && dwell !== '' ? `${Number(dwell).toFixed(1)}s` : '';
    if (entryStr && exitStr) return dwellStr ? `${entryStr} -> ${exitStr} · ${dwellStr}` : `${entryStr} -> ${exitStr}`;
    if (entryStr && dwellStr) return `${entryStr} · ${dwellStr}`;
    return dwellStr ? `Dwell ${dwellStr}` : '';
  }

  function formatAlertDetails(ev) {
    const primary = ev.summary || ev.message || ev.reason || ev.title || JSON.stringify(ev.metadata || {});
    const dwellWindow = formatDwellWindow(ev);
    const promotedBy = ev.metadata?.promoted_by_rule ? ` [Rule: ${ev.metadata.promoted_by_rule}]` : '';
    if (dwellWindow && !String(primary).includes('->') && !String(primary).includes('→')) {
      return `${primary} (${dwellWindow})${promotedBy}`;
    }
    return `${primary}${promotedBy}`;
  }

  function resolveSnapshotSrc(ev) {
    if (ev.snapshot_base64) return `data:image/jpeg;base64,${ev.snapshot_base64}`;
    if (ev.snapshot_url) return ev.snapshot_url;
    if (ev.metadata?.snapshot_url) return ev.metadata.snapshot_url;
    return '';
  }

  function buildAlertRowHtml(ev, idx) {
    const timeStr = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleString() : '--';
    const type = ev.event_type || 'alert';
    const rawSev = String(ev.severity || ev.metadata?.severity || '').toUpperCase();
    let severityClass = 'panel-badge';
    let severityText = rawSev || 'INFO';
    if (rawSev === 'CRITICAL' || rawSev === 'HIGH' || (!rawSev && (type.includes('intrusion') || type.includes('restricted')))) {
      severityClass = 'badge-category restricted';
      severityText = rawSev || 'CRITICAL';
    } else if (rawSev === 'WARNING' || rawSev === 'MEDIUM' || (!rawSev && (type.includes('threshold') || type.includes('capacity')))) {
      severityClass = 'badge-category vip';
      severityText = rawSev || 'WARNING';
    }
    const entityLabel = ev.name || ev.entity_name || ev.suggested_name || (ev.entity_id ? `#${ev.entity_id}` : 'Unknown');
    const detailText = formatAlertDetails(ev);
    const snapSrc = resolveSnapshotSrc(ev);
    const snapshotBtn = snapSrc
      ? `<button type="button" class="btn btn-xs btn-outline btn-alert-snapshot" data-alert-index="${idx}" onclick="window.AlertsView?.openAlertSnapshot?.(${idx})">View</button>`
      : '<span class="text-subtle">None</span>';
    const vFile = ev.video_filename || ev.metadata?.video_filename || '';
    const vOffset = ev.media_offset_sec ?? ev.metadata?.media_offset_sec ?? 0;
    const seekBtn = window.VideoTimelineLinks?.buildSeekInStudioButtonHtml(vFile, vOffset) || '';
    const rowClass = ev.is_read ? 'alert-row-read' : 'alert-row-unread';
    const sourceCell = window.AlertsAdmin?.buildSourceLinkHtml?.(ev) || escapeHtml(ev.zone_id || ev.camera_id || 'System');
    const actionCell = window.AlertsAdmin?.buildActionButtonsHtml?.(ev) || '<span class="text-subtle">--</span>';
    const evId = ev.id !== undefined && ev.id !== null ? String(ev.id) : '';
    const isChecked = state.selectAllMatching || (evId && state.selectedIds.has(evId));
    return `
      <tr class="${rowClass}" data-event-id="${escapeHtml(evId)}" data-is-read="${ev.is_read ? '1' : '0'}">
        <td><input type="checkbox" class="alert-row-select" data-event-id="${escapeHtml(evId)}" ${isChecked ? 'checked' : ''} onchange="window.AlertsView?.toggleRowSelection?.('${escapeHtml(evId)}', this.checked)" /></td>
        <td>${escapeHtml(timeStr)}</td><td><strong>${escapeHtml(type)}</strong></td>
        <td><span class="${severityClass}">${escapeHtml(severityText)}</span></td>
        <td>${sourceCell}</td>
        <td>${escapeHtml(entityLabel)}</td><td>${escapeHtml(detailText)}</td>
        <td>${snapshotBtn}${seekBtn}</td>
        <td>${actionCell}</td>
      </tr>`;
  }

  function syncPaginationControls(itemsCount) {
    const badge = document.getElementById('total-alerts-count');
    const prevBtn = document.getElementById('alerts-prev-btn');
    const nextBtn = document.getElementById('alerts-next-btn');
    const pageInfo = document.getElementById('alerts-page-info');
    if (badge) badge.textContent = `${state.total} event${state.total !== 1 ? 's' : ''}`;
    const pageNum = Math.floor(state.offset / state.limit) + 1;
    const totalPages = Math.max(1, Math.ceil(state.total / state.limit));
    if (pageInfo) pageInfo.textContent = `Page ${pageNum} of ${totalPages} (${itemsCount} shown)`;
    if (prevBtn) prevBtn.disabled = state.offset <= 0;
    if (nextBtn) nextBtn.disabled = !state.hasMore;
  }

  function renderSnapshotOverlay() {
    if (window.SnapshotModalOverlay?.render) return window.SnapshotModalOverlay.render();
    const img = document.getElementById('snapshot-modal-img'), canvas = document.getElementById('snapshot-modal-canvas');
    const U = window.UnifiedCanvasOverlay, ctx = canvas?.getContext?.('2d');
    if (!img || !canvas || !U || !ctx) return;
    const imgRect = img.getBoundingClientRect?.() || { width: img.naturalWidth || 640, height: img.naturalHeight || 360, left: 0, top: 0 };
    const stageRect = img.parentElement?.getBoundingClientRect?.() || imgRect;
    const mediaW = img.naturalWidth || imgRect.width || 640, mediaH = img.naturalHeight || imgRect.height || 360;
    U.syncCanvasDpr(canvas, ctx, stageRect.width || mediaW, stageRect.height || mediaH, window.devicePixelRatio || 1);
    const box = U.computeContainBox(imgRect, stageRect, mediaW, mediaH), ev = state.activePreviewEvent || {};
    const bbox = ev.bbox || ev.metadata?.bbox;
    const scales = U.resolveScaleFactors(box.renderW, box.renderH, ev.source_resolution || ev.metadata?.source_resolution, mediaW, mediaH);
    const tracks = Array.isArray(bbox) && bbox.length >= 4 ? [{ bbox, id: ev.track_id ?? ev.metadata?.track_id, entity_name: ev.entity_name || ev.name || ev.suggested_name, label: ev.event_type || 'alert', confidence: ev.confidence }] : [];
    U.renderScene(ctx, { clear: true, clearWidth: stageRect.width || mediaW, clearHeight: stageRect.height || mediaH, visibility: state.featureVisibility, transform: { offsetX: box.offsetX, offsetY: box.offsetY, scaleX: scales.scaleX, scaleY: scales.scaleY }, tracks, zones: Array.isArray(ev.zones) ? ev.zones : [] });
  }

  function openAlertSnapshot(idx) {
    const ev = state.eventsByIndex[idx], src = ev ? resolveSnapshotSrc(ev) : '';
    if (!ev || !src) return;
    state.activePreviewEvent = ev;
    if (window.SnapshotModalOverlay?.open) return window.SnapshotModalOverlay.open(ev, src, { visibility: state.featureVisibility });
    window.AlertsAdmin?.syncSnapshotDownloadButton?.(src, ev);
    const modal = document.getElementById('modal-snapshot-view'), img = document.getElementById('snapshot-modal-img');
    const metaEl = document.getElementById('snapshot-modal-meta'), controlsEl = document.getElementById('snapshot-modal-controls');
    if (img) { img.onload = () => renderSnapshotOverlay(); img.src = src; }
    if (metaEl) metaEl.textContent = `${ev.event_type || 'alert'} · ${ev.camera_id || 'System'}${ev.zone_id ? ` (${ev.zone_id})` : ''}`;
    if (controlsEl && window.OverlayControlBar?.mount) {
      window.OverlayControlBar.mount({ container: controlsEl, variant: 'scrubber', descriptors: [], showFeaturePills: true, featureVisibility: state.featureVisibility, onToggleFeature: (k, n) => { state.featureVisibility[k] = Boolean(n); renderSnapshotOverlay(); } });
    }
    if (modal) modal.style.display = 'flex';
    if (img?.complete && img?.naturalWidth > 0) renderSnapshotOverlay();
  }

  async function loadAlerts(opts = {}) {
    bindControls();
    if (typeof opts.offset === 'number') state.offset = Math.max(0, opts.offset);
    const tbody = document.getElementById('alerts-table-body');
    if (!tbody) return [];
    try {
      await window.AlertsAdmin?.loadFacets?.();
      await window.AlertRules?.ensureLoaded?.(!opts.filters);
      const res = await fetch(buildEventsUrl(opts.filters || readFiltersFromDom()));
      const payload = await res.json();
      const items = Array.isArray(payload) ? payload : (Array.isArray(payload?.items) ? payload.items : []);
      state.eventsByIndex = items;
      state.total = Array.isArray(payload) ? items.length : Number(payload?.total ?? items.length);
      state.hasMore = Array.isArray(payload) ? false : Boolean(payload?.has_more);
      if (typeof payload?.unread_alert_count === 'number') {
        window.AppUIHelpers?.syncAlertBadges?.(payload.unread_alert_count);
      }
      tbody.innerHTML = items.length
        ? items.map(buildAlertRowHtml).join('')
        : '<tr><td colspan="9" class="text-center">No alerts match the current filters.</td></tr>';
      syncPaginationControls(items.length);
      return items;
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="9" class="text-center">Error loading events: ${escapeHtml(err.message)}</td></tr>`;
      return [];
    }
  }

  function applyFilter(filters = {}) {
    const map = {
      camera_id: 'alerts-filter-camera',
      severity: 'alerts-filter-severity',
      min_severity: 'alerts-filter-min-severity',
      event_type: 'alerts-filter-type',
      zone_id: 'alerts-filter-zone',
    };
    Object.entries(map).forEach(([key, id]) => {
      if (filters[key] !== undefined) {
        const el = document.getElementById(id);
        if (el) el.value = String(filters[key] || '');
      }
    });
    state.offset = typeof filters.offset === 'number' ? Math.max(0, filters.offset) : 0;
    return loadAlerts({ offset: state.offset, filters: { ...readFiltersFromDom(), ...filters } });
  }

  function bindOnce(id, ev, fn) {
    const el = document.getElementById(id);
    if (el && !el.dataset?.bound) {
      if (el.dataset) el.dataset.bound = '1';
      el.addEventListener(ev, fn);
    }
  }

  function bindControls() {
    window.AlertsAdmin?.bindAdminControls?.(readFiltersFromDom);
    window.AlertRules?.bindControls?.();
    bindOnce('alerts-filter-apply', 'click', () => { state.offset = 0; loadAlerts(); });
    bindOnce('alerts-filter-reset', 'click', () => {
      ['alerts-filter-camera', 'alerts-filter-severity', 'alerts-filter-min-severity', 'alerts-filter-type', 'alerts-filter-zone'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.value = '';
      });
      state.offset = 0;
      loadAlerts({ filters: readFiltersFromDom() });
    });
    bindOnce('alerts-prev-btn', 'click', () => { state.offset = Math.max(0, state.offset - state.limit); loadAlerts(); });
    bindOnce('alerts-next-btn', 'click', () => { if (state.hasMore) { state.offset += state.limit; loadAlerts(); } });
    bindOnce('alerts-select-all', 'change', (e) => toggleSelectAllVisible(Boolean(e.target?.checked)));
    bindOnce('alerts-select-all-matching', 'change', (e) => toggleSelectAllMatching(Boolean(e.target?.checked)));
    bindOnce('btn-alerts-ack-selected', 'click', () => bulkAckSelected(true));
    bindOnce('btn-alerts-delete-selected', 'click', () => bulkDeleteSelected());
  }

  function toggleRowSelection(eventId, checked) {
    if (!eventId) return;
    if (checked) state.selectedIds.add(String(eventId));
    else { state.selectedIds.delete(String(eventId)); state.selectAllMatching = false; }
  }

  function toggleSelectAllVisible(checked) {
    state.selectAllMatching = false;
    state.eventsByIndex.forEach((ev) => {
      if (ev?.id === undefined || ev?.id === null) return;
      if (checked) state.selectedIds.add(String(ev.id));
      else state.selectedIds.delete(String(ev.id));
    });
    document.querySelectorAll?.('.alert-row-select')?.forEach?.((cb) => { cb.checked = checked; });
  }

  function toggleSelectAllMatching(checked) {
    state.selectAllMatching = Boolean(checked);
    toggleSelectAllVisible(Boolean(checked));
    state.selectAllMatching = Boolean(checked);
  }

  async function bulkAckSelected(isRead = true) {
    if (state.selectAllMatching) {
      return window.AlertsAdmin?.acknowledgeEvents?.({ markAll: true, isRead });
    }
    const ids = Array.from(state.selectedIds).map((id) => Number(id)).filter(Number.isFinite);
    if (!ids.length) return null;
    state.selectedIds.clear();
    return window.AlertsAdmin?.acknowledgeEvents?.({ eventIds: ids, isRead });
  }

  async function bulkDeleteSelected() {
    if (state.selectAllMatching) {
      state.selectAllMatching = false;
      state.selectedIds.clear();
      return window.AlertsAdmin?.clearMatchingEvents?.(readFiltersFromDom());
    }
    const ids = Array.from(state.selectedIds);
    if (!ids.length) return null;
    state.selectedIds.clear();
    for (const id of ids) {
      await window.AlertsAdmin?.deleteEvent?.(id);
    }
    return { deleted: ids.length };
  }

  window.AlertsView = {
    state,
    buildEventsUrl,
    loadAlerts,
    applyFilter,
    openAlertSnapshot,
    renderSnapshotOverlay,
    bindControls,
    toggleRowSelection,
    toggleSelectAllVisible,
    toggleSelectAllMatching,
    bulkAckSelected,
    bulkDeleteSelected,
  };
})();
