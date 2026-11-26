/**
 * Intelligent Tracker - Security Alerts Filter, Pagination & Snapshot Canvas Preview.
 * Reuses UnifiedCanvasOverlay + OverlayControlBar inside #modal-snapshot-view.
 */
(function () {
  'use strict';

  const state = {
    offset: 0,
    limit: 50,
    total: 0,
    hasMore: false,
    eventsByIndex: [],
    featureVisibility: {
      bboxes: true, track_ids: true, dwell_timers: true,
      velocity: false, zones: true, tripwires: true,
    },
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
    const typeEl = document.getElementById('alerts-filter-type');
    const zoneEl = document.getElementById('alerts-filter-zone');
    return {
      camera_id: (camEl?.value ?? window.App?.getActiveCameraId?.() ?? '').trim(),
      severity: (sevEl?.value || '').trim(),
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
    if (filters.event_type) params.set('event_type', filters.event_type);
    if (filters.zone_id) params.set('zone_id', filters.zone_id);
    if (filters.start_time !== undefined && filters.start_time !== '') params.set('start_time', String(filters.start_time));
    if (filters.end_time !== undefined && filters.end_time !== '') params.set('end_time', String(filters.end_time));
    return `/events?${params.toString()}`;
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
    const detailText = ev.message || ev.reason || ev.title || ev.summary || JSON.stringify(ev.metadata || {});
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
    return `
      <tr class="${rowClass}" data-event-id="${escapeHtml(ev.id ?? '')}" data-is-read="${ev.is_read ? '1' : '0'}">
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
    const img = document.getElementById('snapshot-modal-img');
    const canvas = document.getElementById('snapshot-modal-canvas');
    const U = window.UnifiedCanvasOverlay;
    if (!img || !canvas || !U) return;
    const ctx = canvas.getContext?.('2d');
    if (!ctx) return;
    const imgRect = img.getBoundingClientRect?.() || { width: img.naturalWidth || 640, height: img.naturalHeight || 360, left: 0, top: 0 };
    const stageRect = img.parentElement?.getBoundingClientRect?.() || imgRect;
    const mediaW = img.naturalWidth || imgRect.width || 640;
    const mediaH = img.naturalHeight || imgRect.height || 360;
    U.syncCanvasDpr(canvas, ctx, stageRect.width || mediaW, stageRect.height || mediaH, window.devicePixelRatio || 1);
    const box = U.computeContainBox(imgRect, stageRect, mediaW, mediaH);
    const ev = state.activePreviewEvent || {};
    const bbox = ev.bbox || ev.metadata?.bbox;
    const scales = U.resolveScaleFactors(box.renderW, box.renderH, ev.source_resolution || ev.metadata?.source_resolution, mediaW, mediaH);
    const tracks = Array.isArray(bbox) && bbox.length >= 4 ? [{
      bbox,
      id: ev.track_id ?? ev.metadata?.track_id,
      entity_name: ev.entity_name || ev.name || ev.suggested_name,
      label: ev.event_type || 'alert',
      confidence: ev.confidence,
    }] : [];
    U.renderScene(ctx, {
      clear: true,
      clearWidth: stageRect.width || mediaW,
      clearHeight: stageRect.height || mediaH,
      visibility: state.featureVisibility,
      transform: { offsetX: box.offsetX, offsetY: box.offsetY, scaleX: scales.scaleX, scaleY: scales.scaleY },
      tracks,
      zones: Array.isArray(ev.zones) ? ev.zones : [],
    });
  }

  function openAlertSnapshot(idx) {
    const ev = state.eventsByIndex[idx];
    if (!ev) return;
    const src = resolveSnapshotSrc(ev);
    if (!src) return;
    state.activePreviewEvent = ev;
    window.AlertsAdmin?.syncSnapshotDownloadButton?.(src, ev);
    const modal = document.getElementById('modal-snapshot-view');
    const img = document.getElementById('snapshot-modal-img');
    const metaEl = document.getElementById('snapshot-modal-meta');
    const controlsEl = document.getElementById('snapshot-modal-controls');
    if (img) {
      img.onload = () => renderSnapshotOverlay();
      img.src = src;
    }
    if (metaEl) {
      metaEl.textContent = `${ev.event_type || 'alert'} · ${ev.camera_id || 'System'}${ev.zone_id ? ` (${ev.zone_id})` : ''}`;
    }
    if (controlsEl && window.OverlayControlBar?.mount) {
      window.OverlayControlBar.mount({
        container: controlsEl,
        variant: 'scrubber',
        descriptors: [],
        showFeaturePills: true,
        featureVisibility: state.featureVisibility,
        onToggleFeature: (key, next) => {
          state.featureVisibility[key] = Boolean(next);
          renderSnapshotOverlay();
        },
      });
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
        : '<tr><td colspan="8" class="text-center">No alerts match the current filters.</td></tr>';
      syncPaginationControls(items.length);
      return items;
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center">Error loading events: ${escapeHtml(err.message)}</td></tr>`;
      return [];
    }
  }

  function applyFilter(filters = {}) {
    const map = {
      camera_id: 'alerts-filter-camera',
      severity: 'alerts-filter-severity',
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

  function bindControls() {
    window.AlertsAdmin?.bindAdminControls?.(readFiltersFromDom);
    const applyBtn = document.getElementById('alerts-filter-apply');
    const resetBtn = document.getElementById('alerts-filter-reset');
    const prevBtn = document.getElementById('alerts-prev-btn');
    const nextBtn = document.getElementById('alerts-next-btn');
    if (applyBtn && !applyBtn.dataset.bound) {
      applyBtn.dataset.bound = '1';
      applyBtn.addEventListener('click', () => { state.offset = 0; loadAlerts(); });
    }
    if (resetBtn && !resetBtn.dataset.bound) {
      resetBtn.dataset.bound = '1';
      resetBtn.addEventListener('click', () => {
        ['alerts-filter-camera', 'alerts-filter-severity', 'alerts-filter-type', 'alerts-filter-zone'].forEach((id) => {
          const el = document.getElementById(id);
          if (el) el.value = '';
        });
        state.offset = 0;
        loadAlerts();
      });
    }
    if (prevBtn && !prevBtn.dataset.bound) {
      prevBtn.dataset.bound = '1';
      prevBtn.addEventListener('click', () => {
        state.offset = Math.max(0, state.offset - state.limit);
        loadAlerts();
      });
    }
    if (nextBtn && !nextBtn.dataset.bound) {
      nextBtn.dataset.bound = '1';
      nextBtn.addEventListener('click', () => {
        if (!state.hasMore) return;
        state.offset += state.limit;
        loadAlerts();
      });
    }
  }

  window.AlertsView = {
    state,
    buildEventsUrl,
    loadAlerts,
    applyFilter,
    openAlertSnapshot,
    renderSnapshotOverlay,
    bindControls,
  };
})();
