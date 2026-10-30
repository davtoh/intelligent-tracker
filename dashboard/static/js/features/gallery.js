/**
 * Intelligent Tracker - Entity Gallery Controller (Tab 2).
 * Handles persistent entity cards, category filtering, search, and deletion.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  const escapeHtml = window.escapeHtml || (s => s);
  let allGalleryEntities = [];

  const galleryGrid = document.getElementById('entity-gallery-grid');
  const gallerySearch = document.getElementById('gallery-search-input');
  const galleryCategoryFilters = document.getElementById('gallery-category-filters');

  async function loadGallery() {
    if (!galleryGrid) return;
    try {
      const res = await fetch('/entities');
      allGalleryEntities = await res.json();
      renderGalleryGrid();
    } catch (err) {
      galleryGrid.innerHTML = `<div class="empty-state">Error loading gallery: ${escapeHtml(err.message)}</div>`;
    }
  }

  function renderGalleryGrid() {
    if (!galleryGrid) return;
    const query = gallerySearch ? gallerySearch.value.toLowerCase().trim() : '';
    const activeCategory = document.querySelector('.filter-pill.active')?.getAttribute('data-category') || '';

    const filtered = allGalleryEntities.filter(ent => {
      const matchesQuery = !query || ent.name.toLowerCase().includes(query) || (ent.notes && ent.notes.toLowerCase().includes(query));
      const matchesCat = !activeCategory || ent.category === activeCategory;
      return matchesQuery && matchesCat;
    });

    if (!filtered.length) {
      galleryGrid.innerHTML = '<div class="empty-state">No entities match your filter criteria. Click "Enroll New Identity" to add one.</div>';
      return;
    }

    galleryGrid.innerHTML = filtered.map(ent => {
      const thumb = ent.thumbnail_url || '/static/avatar-placeholder.png';
      const cat = ent.category || 'person';
      return `
        <div class="glass-panel entity-card" data-id="${ent.id}">
          <div class="entity-card-top">
            <img class="entity-avatar" src="${thumb}" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'60\\' height=\\'60\\' fill=\\'%2364748b\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%231e293b\\'/><text x=\\'50%\\' y=\\'55%\\' font-size=\\'22\\' text-anchor=\\'middle\\' fill=\\'%2394a3b8\\' font-family=\\'sans-serif\\'>${escapeHtml(ent.name.charAt(0))}</text></svg>'" alt="${escapeHtml(ent.name)}" />
            <div class="entity-meta">
              <div class="entity-name">${escapeHtml(ent.name)}</div>
              <span class="badge-category ${cat}">${cat}</span>
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
        </div>
      `;
    }).join('');

    // Attach Action Listeners
    document.querySelectorAll('.btn-view-sightings').forEach(btn => {
      btn.addEventListener('click', () => {
        const entId = btn.getAttribute('data-id');
        if (window.TrackerApp.switchTab) {
          window.TrackerApp.switchTab('tab-timeline');
        }
        const timelineSelectEntity = document.getElementById('timeline-entity-select');
        if (timelineSelectEntity) {
          timelineSelectEntity.value = entId;
        }
        if (window.TrackerApp.Timeline?.loadSightings) {
          window.TrackerApp.Timeline.loadSightings();
        }
      });
    });

    document.querySelectorAll('.btn-view-versions').forEach(btn => {
      btn.addEventListener('click', () => {
        const entId = btn.getAttribute('data-id');
        const entName = btn.getAttribute('data-name');
        if (window.ReviewAndRSAC && typeof window.ReviewAndRSAC.openVersionsModal === 'function') {
          window.ReviewAndRSAC.openVersionsModal(entId, entName);
        }
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

  function initGallery() {
    gallerySearch?.addEventListener('input', renderGalleryGrid);
    galleryCategoryFilters?.querySelectorAll('.filter-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        galleryCategoryFilters.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        renderGalleryGrid();
      });
    });
  }

  // Auto-init when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initGallery);
  } else {
    initGallery();
  }

  window.TrackerApp.Gallery = {
    load: loadGallery,
    render: renderGalleryGrid,
  };
})();

