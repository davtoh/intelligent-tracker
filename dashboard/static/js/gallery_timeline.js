/**
 * Intelligent Tracker - Entity Gallery & Sighting Timeline Submodule.
 * Handles enrolled gallery grid rendering, category filtering, sighting queries, and snapshot viewer.
 */

(function () {
  'use strict';

  let allGalleryEntities = [];
  let timelineOffset = 0;
  let timelineTotal = 0;
  let timelineHasMore = false;
  let timelineVideoFilename = '';
  let timelineStartTime = '';
  let timelineEndTime = '';

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function resetGalleryFilters() {
    const gs = document.getElementById('gallery-search-input');
    if (gs) gs.value = '';
    document.querySelectorAll('#gallery-category-filters .filter-pill').forEach(p => p.classList.toggle('active', !p.getAttribute('data-category')));
  }

  async function loadGallery(options = {}) {
    const galleryGrid = document.getElementById('entity-gallery-grid');
    if (!galleryGrid) return;
    try {
      const res = await fetch('/entities');
      allGalleryEntities = await res.json();
      const ent = options?.highlightEntityId != null && Array.isArray(allGalleryEntities)
        ? allGalleryEntities.find(e => String(e.id) === String(options.highlightEntityId)) : null;
      const q = (document.getElementById('gallery-search-input')?.value || '').toLowerCase().trim();
      const cat = document.querySelector('.filter-pill.active')?.getAttribute('data-category') || '';
      if (ent && ((q && !ent.name?.toLowerCase().includes(q) && !ent.notes?.toLowerCase().includes(q)) || (cat && ent.category !== cat))) resetGalleryFilters();
      renderGalleryGrid();
    } catch (err) {
      galleryGrid.innerHTML = `<div class="empty-state">Error loading gallery: ${escapeHtml(err.message)}</div>`;
    }
  }

  function buildEntityCardHtml(ent) {
    const thumb = ent.thumbnail_url || '/static/avatar-placeholder.svg';
    const cat = ent.category || 'person';
    const badgeHtml = window.CategoryBadgeManager?.renderBadgeHtml ? window.CategoryBadgeManager.renderBadgeHtml(cat) : `<span class="badge-category ${cat}">${escapeHtml(cat)}</span>`;
    return `
      <div class="glass-panel entity-card" data-id="${ent.id}">
        <div class="entity-card-top">
          <img class="entity-avatar" src="${thumb}" onerror="this.onerror=null;this.src='/static/avatar-placeholder.svg';" alt="${escapeHtml(ent.name)}" />
          <div class="entity-meta">
            <div class="entity-name">${escapeHtml(ent.name)}</div>
            ${badgeHtml}
          </div>
        </div>
        <div class="entity-stats">
          <span>Appearances: <strong>${ent.appearance_count || 0}</strong></span>
          <span>Signatures: <strong>${ent.signature_count || 0}</strong></span>
        </div>
        <div class="entity-actions">
          <button class="btn btn-xs btn-outline btn-view-sightings" data-id="${ent.id}" data-name="${escapeHtml(ent.name)}">Sightings</button>
          <button class="btn btn-xs btn-outline btn-view-versions" data-id="${ent.id}" data-name="${escapeHtml(ent.name)}" title="Descriptor Version History & Rollback">⏳ Versions</button>
          <button class="btn btn-xs btn-outline btn-delete-entity" data-id="${ent.id}" style="color: #ef4444;">Delete</button>
        </div>
      </div>`;
  }

  function renderGalleryGrid() {
    const galleryGrid = document.getElementById('entity-gallery-grid');
    const gallerySearch = document.getElementById('gallery-search-input');
    if (!galleryGrid) return;

    const query = gallerySearch ? gallerySearch.value.toLowerCase().trim() : '';
    const activeCategory = document.querySelector('.filter-pill.active')?.getAttribute('data-category') || '';
    const filtered = allGalleryEntities.filter(ent => {
      const matchesQuery = !query || ent.name.toLowerCase().includes(query) || (ent.notes && ent.notes.toLowerCase().includes(query));
      return matchesQuery && (!activeCategory || ent.category === activeCategory);
    });

    if (!filtered.length) {
      galleryGrid.innerHTML = '<div class="empty-state">No entities match your filter criteria. Click "Enroll New Identity" to add one.</div>';
      return;
    }
    galleryGrid.innerHTML = filtered.map(buildEntityCardHtml).join('');
    bindGalleryActionButtons();
  }

  function bindGalleryActionButtons() {
    document.querySelectorAll('.btn-view-sightings').forEach(btn => {
      btn.addEventListener('click', async () => {
        const entId = btn.getAttribute('data-id');
        if (window.App?.navigate) return window.App.navigate('tab-timeline', { entityId: entId });
        window.switchTab?.('tab-timeline');
        await loadTimelineFilters();
        const sel = document.getElementById('timeline-entity-select');
        if (sel) sel.value = entId;
        await loadSightings();
      });
    });

    document.querySelectorAll('.btn-view-versions').forEach(btn => {
      btn.addEventListener('click', () => {
        const entId = btn.getAttribute('data-id');
        const entName = btn.getAttribute('data-name');
        window.ReviewAndRSAC?.openVersionsModal?.(entId, entName);
      });
    });

    document.querySelectorAll('.btn-delete-entity').forEach(btn => {
      btn.addEventListener('click', async () => {
        const entId = btn.getAttribute('data-id');
        if (confirm('Are you sure you want to delete this identity and its visual signatures?')) {
          await fetch(`/entities/${entId}`, { method: 'DELETE' });
          loadGallery();
        }
      });
    });
  }

  function bindGalleryEvents() {
    document.getElementById('gallery-search-input')?.addEventListener('input', renderGalleryGrid);
    document.getElementById('gallery-category-filters')?.querySelectorAll('.filter-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('#gallery-category-filters .filter-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        renderGalleryGrid();
      });
    });
    document.getElementById('btn-enroll-modal')?.addEventListener('click', () => {
      if (window.UniversalEnrollment?.openModal) window.UniversalEnrollment.openModal();
      else window.InteractiveCanvas?.openTagModal?.(null);
    });
    window.CategoryBadgeManager?.init?.(renderGalleryGrid);
  }

  async function loadTimelineFilters() {
    const timelineSelectEntity = document.getElementById('timeline-entity-select');
    const timelineSelectZone = document.getElementById('timeline-zone-select');
    const timelineSelectSource = document.getElementById('timeline-source-select');
    if (!timelineSelectEntity || !timelineSelectZone) return;

    try {
      const [entRes, zoneRes, srcRes] = await Promise.all([
        fetch('/entities'),
        fetch('/zones'),
        fetch('/sightings/sources').catch(() => null),
      ]);
      const [entities, zones] = await Promise.all([entRes.json(), zoneRes.json()]);
      const sources = srcRes && typeof srcRes.json === 'function' ? await srcRes.json().catch(() => []) : [];
      timelineSelectEntity.innerHTML = '<option value="">All Entities</option>' +
        (Array.isArray(entities) ? entities : []).map(e => `<option value="${e.id}">${escapeHtml(e.name)} (${escapeHtml(e.category)})</option>`).join('');
      timelineSelectZone.innerHTML = '<option value="">All Zones</option>' +
        (Array.isArray(zones) ? zones : []).map(z => `<option value="${escapeHtml(z.name)}">${escapeHtml(z.name)}</option>`).join('');
      if (timelineSelectSource) {
        const prevSrc = timelineSelectSource.value;
        timelineSelectSource.innerHTML = '<option value="">All Sources</option>' +
          (Array.isArray(sources) ? sources : []).map(s => {
            const srcName = typeof s === 'string' ? s : s.source;
            const cnt = typeof s === 'object' && s.count != null ? ` (${s.count})` : '';
            return `<option value="${escapeHtml(srcName)}">${escapeHtml(srcName)}${cnt}</option>`;
          }).join('');
        if (prevSrc) timelineSelectSource.value = prevSrc;
      }
    } catch (err) {
      console.error('Filter load error:', err);
    }
  }

  function jumpToLiveSource(source) {
    if (!source) return false;
    if (window.App?.navigate) {
      window.App.navigate('tab-live', { cameraId: source });
      return true;
    }
    window.switchTab?.('tab-live');
    window.App?.switchCamera?.(source);
    return true;
  }

  function buildSightingCardHtml(s) {
    const timeStr = s.timestamp || 'Unknown';
    const snap = s.snapshot_url || '/static/avatar-placeholder.svg';
    const name = s.entity_name || 'Unidentified Track';
    const cat = s.entity_category || 'person';
    const confPct = s.confidence ? (s.confidence * 100).toFixed(0) : '100';
    const sourceLabel = s.source || s.video_filename || 'Unknown';
    const seekBtn = window.VideoTimelineLinks?.buildSeekInStudioButtonHtml(s.video_filename, s.media_offset_sec) || '';
    const liveBtn = (!s.video_filename && s.source)
      ? `<button type="button" class="btn btn-xs btn-outline btn-jump-live" data-source="${escapeHtml(s.source)}" onclick="window.TimelineView?.jumpToLiveSource?.(this.getAttribute('data-source'))" title="Open ${escapeHtml(s.source)} in Live Monitor">📡 Live Monitor</button>`
      : '';
    return `
      <div class="timeline-node">
        <div class="timeline-dot"></div>
        <div class="glass-panel timeline-card">
          <img class="timeline-thumbnail" src="${snap}" onerror="this.style.display='none'" alt="Snapshot" onclick="showSnapshotModal('${snap}', '${escapeHtml(name)} - ${escapeHtml(timeStr)}')" />
          <div class="timeline-content">
            <div class="timeline-title">
              <span>${escapeHtml(name)}</span>
              <span class="badge-category ${cat}">${escapeHtml(cat)}</span>
              <span class="panel-badge timeline-source-badge">📷 ${escapeHtml(sourceLabel)}</span>
              <span class="panel-badge">Zone: ${escapeHtml(s.zone_id || 'Free space')}</span>
            </div>
            <div class="timeline-meta">
              <span>🕒 ${escapeHtml(timeStr)}</span> &bull;
              <span>Track #${s.track_id}</span> &bull;
              <span>Match Confidence: ${confPct}%</span>
              ${seekBtn}${liveBtn}${window.ReviewUndoAndFlag?.buildReportWrongButtonHtml?.(s) || ''}
            </div>
          </div>
        </div>
      </div>`;
  }

  function updateTimelinePaginationBar(limit) {
    const prevBtn = document.getElementById('timeline-prev-btn');
    const nextBtn = document.getElementById('timeline-next-btn');
    const pageInfo = document.getElementById('timeline-page-info');
    if (prevBtn) prevBtn.disabled = timelineOffset <= 0;
    if (nextBtn) nextBtn.disabled = !timelineHasMore;
    if (pageInfo) {
      const safeLimit = Math.max(1, Number(limit) || 50);
      const pageNum = Math.floor(timelineOffset / safeLimit) + 1;
      const totalPages = Math.max(1, Math.ceil(timelineTotal / safeLimit));
      pageInfo.textContent = timelineTotal > 0
        ? `Page ${pageNum} of ${totalPages} (${timelineTotal} total)`
        : 'Page 1 of 1';
    }
  }

  async function loadSightings(options = {}) {
    const timelineList = document.getElementById('sightings-timeline-list');
    if (!timelineList) return;
    if (options && (options.resetOffset === true || typeof options.preventDefault === 'function')) {
      timelineOffset = 0;
    }
    const entId = document.getElementById('timeline-entity-select')?.value;
    const zoneId = document.getElementById('timeline-zone-select')?.value;
    const sourceVal = document.getElementById('timeline-source-select')?.value;
    const limit = Number(document.getElementById('timeline-limit-select')?.value || 50);
    let url = `/sightings?paginated=true&limit=${limit}&offset=${timelineOffset}`;
    if (entId) url += `&entity_id=${entId}`;
    if (zoneId) url += `&zone_id=${encodeURIComponent(zoneId)}`;
    if (sourceVal) url += `&source=${encodeURIComponent(sourceVal)}`;
    if (timelineVideoFilename) url += `&video_filename=${encodeURIComponent(timelineVideoFilename)}`;
    if (timelineStartTime !== '') url += `&start_time=${encodeURIComponent(timelineStartTime)}`;
    if (timelineEndTime !== '') url += `&end_time=${encodeURIComponent(timelineEndTime)}`;
    timelineList.innerHTML = '<div class="empty-state">Loading sightings...</div>';
    try {
      const res = await fetch(url);
      const payload = await res.json();
      const sightings = Array.isArray(payload) ? payload : (payload.items || []);
      timelineTotal = Array.isArray(payload) ? sightings.length : Number(payload.total || 0);
      timelineHasMore = Array.isArray(payload) ? false : Boolean(payload.has_more);
      timelineList.innerHTML = sightings.length
        ? sightings.map(buildSightingCardHtml).join('')
        : '<div class="empty-state">No matching sightings found for selected parameters.</div>';
      updateTimelinePaginationBar(limit);
    } catch (err) {
      timelineList.innerHTML = `<div class="empty-state">Error querying sightings: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function applyTimelineFilter(opts = {}) {
    const entSel = document.getElementById('timeline-entity-select'), zoneSel = document.getElementById('timeline-zone-select');
    const srcSel = document.getElementById('timeline-source-select'), limSel = document.getElementById('timeline-limit-select');
    if (opts.entityId !== undefined && entSel) entSel.value = opts.entityId || '';
    if (opts.zoneId !== undefined && zoneSel) zoneSel.value = opts.zoneId || '';
    if (opts.source !== undefined && srcSel) srcSel.value = opts.source || '';
    if (opts.limit !== undefined && limSel) limSel.value = String(opts.limit);
    timelineVideoFilename = opts.videoFilename || '';
    timelineStartTime = opts.startTime ?? opts.from ?? '';
    timelineEndTime = opts.endTime ?? opts.to ?? '';
    timelineOffset = Math.max(0, Number(opts.offset || 0));
    window.TimelineFilterHelpers?.syncActiveWindowChip?.({ startTime: timelineStartTime, endTime: timelineEndTime, videoFilename: timelineVideoFilename });
    await loadSightings();
  }

  async function resetTimelineFilters() {
    timelineVideoFilename = ''; timelineStartTime = ''; timelineEndTime = ''; timelineOffset = 0;
    window.TimelineFilterHelpers?.resetTimelineInputs?.();
    window.TimelineFilterHelpers?.syncActiveWindowChip?.({});
    window.TimelineFilterHelpers?.clearTimelineUrlHash?.();
    await loadSightings({ resetOffset: true });
  }

  function bindTimelineEvents() {
    const resetAndLoad = () => loadSightings({ resetOffset: true });
    document.getElementById('btn-filter-sightings')?.addEventListener('click', resetAndLoad);
    document.getElementById('btn-reset-timeline-filters')?.addEventListener('click', resetTimelineFilters);
    ['timeline-entity-select', 'timeline-zone-select', 'timeline-source-select', 'timeline-limit-select'].forEach(id => document.getElementById(id)?.addEventListener('change', resetAndLoad));
    document.getElementById('timeline-prev-btn')?.addEventListener('click', () => { timelineOffset = Math.max(0, timelineOffset - Number(document.getElementById('timeline-limit-select')?.value || 50)); loadSightings(); });
    document.getElementById('timeline-next-btn')?.addEventListener('click', () => { if (!timelineHasMore) return; timelineOffset += Number(document.getElementById('timeline-limit-select')?.value || 50); loadSightings(); });
  }

  function showSnapshotModal(imgUrl, title) {
    window.SnapshotModalOverlay?.reset?.();
    const modalSnapshot = document.getElementById('modal-snapshot-view');
    const modalSnapshotImg = document.getElementById('snapshot-modal-img');
    const modalSnapshotMeta = document.getElementById('snapshot-modal-meta');
    if (modalSnapshot && modalSnapshotImg && modalSnapshotMeta) {
      modalSnapshotImg.src = imgUrl;
      modalSnapshotMeta.textContent = title;
      modalSnapshot.style.display = 'flex';
    }
  }

  function initSnapshotModal() {
    document.getElementById('modal-snapshot-close')?.addEventListener('click', () => {
      window.SnapshotModalOverlay?.reset?.();
      const modal = document.getElementById('modal-snapshot-view');
      if (modal) modal.style.display = 'none';
    });
    document.getElementById('btn-snapshot-save')?.addEventListener('click', async () => {
      const camId = window.App?.getActiveCameraId?.();
      if (!camId) return;
      try {
        const res = await fetch(`/api/cameras/${encodeURIComponent(camId)}/freeze_frame`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!data.image_base64) return;
        const a = document.createElement('a');
        a.href = data.image_base64;
        a.download = `snapshot_${camId}_${Date.now()}.jpg`;
        document.body?.appendChild?.(a);
        a.click();
        a.remove?.();
      } catch (err) {
        window.showToast?.('Snapshot Error', err.message, 'error');
      }
    });
  }

  window.GalleryTimeline = {
    loadGallery, resetGalleryFilters, renderGalleryGrid, bindGalleryEvents, loadTimelineFilters,
    loadSightings, bindTimelineEvents, showSnapshotModal, initSnapshotModal,
  };
  window.TimelineView = {
    applyFilter: applyTimelineFilter, resetFilters: resetTimelineFilters,
    loadSightings, loadTimelineFilters, jumpToLiveSource,
  };
})();

