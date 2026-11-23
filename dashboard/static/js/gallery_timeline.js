/**
 * Intelligent Tracker - Entity Gallery & Sighting Timeline Submodule.
 * Handles enrolled gallery grid rendering, category filtering, sighting queries, and snapshot viewer.
 */

(function () {
  'use strict';

  let allGalleryEntities = [];

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  async function loadGallery() {
    const galleryGrid = document.getElementById('entity-gallery-grid');
    if (!galleryGrid) return;
    try {
      const res = await fetch('/entities');
      allGalleryEntities = await res.json();
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
    if (!timelineSelectEntity || !timelineSelectZone) return;

    try {
      const [entRes, zoneRes] = await Promise.all([fetch('/entities'), fetch('/zones')]);
      const entities = await entRes.json();
      const zones = await zoneRes.json();

      timelineSelectEntity.innerHTML = '<option value="">All Entities</option>' +
        entities.map(e => `<option value="${e.id}">${escapeHtml(e.name)} (${escapeHtml(e.category)})</option>`).join('');

      timelineSelectZone.innerHTML = '<option value="">All Zones</option>' +
        zones.map(z => `<option value="${escapeHtml(z.name)}">${escapeHtml(z.name)}</option>`).join('');
    } catch (err) {
      console.error('Filter load error:', err);
    }
  }

  function buildSightingCardHtml(s) {
    const timeStr = s.timestamp || 'Unknown';
    const snap = s.snapshot_url || '/static/avatar-placeholder.svg';
    const name = s.entity_name || 'Unidentified Track';
    const cat = s.entity_category || 'person';
    const confPct = s.confidence ? (s.confidence * 100).toFixed(0) : '100';
    const seekBtn = window.VideoTimelineLinks?.buildSeekInStudioButtonHtml(s.video_filename, s.media_offset_sec) || '';
    return `
      <div class="timeline-node">
        <div class="timeline-dot"></div>
        <div class="glass-panel timeline-card">
          <img class="timeline-thumbnail" src="${snap}" onerror="this.style.display='none'" alt="Snapshot" onclick="showSnapshotModal('${snap}', '${escapeHtml(name)} - ${escapeHtml(timeStr)}')" />
          <div class="timeline-content">
            <div class="timeline-title">
              <span>${escapeHtml(name)}</span>
              <span class="badge-category ${cat}">${escapeHtml(cat)}</span>
              <span class="panel-badge">Zone: ${escapeHtml(s.zone_id || 'Free space')}</span>
            </div>
            <div class="timeline-meta">
              <span>🕒 ${escapeHtml(timeStr)}</span> &bull;
              <span>Track #${s.track_id}</span> &bull;
              <span>Match Confidence: ${confPct}%</span>
              ${seekBtn}
            </div>
          </div>
        </div>
      </div>`;
  }

  async function loadSightings() {
    const timelineList = document.getElementById('sightings-timeline-list');
    if (!timelineList) return;
    const entId = document.getElementById('timeline-entity-select')?.value;
    const zoneId = document.getElementById('timeline-zone-select')?.value;
    const limit = document.getElementById('timeline-limit-select')?.value || 50;
    let url = `/sightings?limit=${limit}`;
    if (entId) url += `&entity_id=${entId}`;
    if (zoneId) url += `&zone_id=${encodeURIComponent(zoneId)}`;
    timelineList.innerHTML = '<div class="empty-state">Loading sightings...</div>';
    try {
      const res = await fetch(url);
      const sightings = await res.json();
      timelineList.innerHTML = sightings.length
        ? sightings.map(buildSightingCardHtml).join('')
        : '<div class="empty-state">No matching sightings found for selected parameters.</div>';
    } catch (err) {
      timelineList.innerHTML = `<div class="empty-state">Error querying sightings: ${escapeHtml(err.message)}</div>`;
    }
  }

  function bindTimelineEvents() {
    document.getElementById('btn-filter-sightings')?.addEventListener('click', loadSightings);
  }

  function showSnapshotModal(imgUrl, title) {
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
    loadGallery: loadGallery,
    renderGalleryGrid: renderGalleryGrid,
    bindGalleryEvents: bindGalleryEvents,
    loadTimelineFilters: loadTimelineFilters,
    loadSightings: loadSightings,
    bindTimelineEvents: bindTimelineEvents,
    showSnapshotModal: showSnapshotModal,
    initSnapshotModal: initSnapshotModal,
  };
})();

