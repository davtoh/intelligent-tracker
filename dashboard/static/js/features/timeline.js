/**
 * Intelligent Tracker - Sighting Timeline Controller (Tab 3).
 * Queries historical sightings, filters by entity or zone, and renders timeline nodes.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  const escapeHtml = window.escapeHtml || (s => s);

  const timelineSelectEntity = document.getElementById('timeline-entity-select');
  const timelineSelectZone = document.getElementById('timeline-zone-select');
  const timelineSelectLimit = document.getElementById('timeline-limit-select');
  const timelineList = document.getElementById('sightings-timeline-list');
  const btnFilterSightings = document.getElementById('btn-filter-sightings');

  const modalSnapshot = document.getElementById('modal-snapshot-view');
  const modalSnapshotImg = document.getElementById('snapshot-modal-img');
  const modalSnapshotMeta = document.getElementById('snapshot-modal-meta');
  const modalSnapshotClose = document.getElementById('modal-snapshot-close');

  async function loadTimelineFilters() {
    if (!timelineSelectEntity || !timelineSelectZone) return;
    try {
      const [entRes, zoneRes] = await Promise.all([fetch('/entities'), fetch('/zones')]);
      const entities = await entRes.json();
      const zones = await zoneRes.json();

      timelineSelectEntity.innerHTML = '<option value="">All Entities</option>' +
        entities.map(e => `<option value="${e.id}">${escapeHtml(e.name)} (${e.category})</option>`).join('');

      timelineSelectZone.innerHTML = '<option value="">All Zones</option>' +
        zones.map(z => `<option value="${escapeHtml(z.name)}">${escapeHtml(z.name)}</option>`).join('');
    } catch (err) {
      console.error('Filter load error:', err);
    }
  }

  async function loadSightings() {
    if (!timelineList) return;
    const entId = timelineSelectEntity?.value || '';
    const zoneId = timelineSelectZone?.value || '';
    const limit = timelineSelectLimit?.value || 50;

    let url = `/sightings?limit=${limit}`;
    if (entId) url += `&entity_id=${entId}`;
    if (zoneId) url += `&zone_id=${encodeURIComponent(zoneId)}`;

    timelineList.innerHTML = '<div class="empty-state">Loading sightings...</div>';

    try {
      const res = await fetch(url);
      const sightings = await res.json();

      if (!sightings.length) {
        timelineList.innerHTML = '<div class="empty-state">No matching sightings found for selected parameters.</div>';
        return;
      }

      timelineList.innerHTML = sightings.map(s => {
        const timeStr = s.timestamp || 'Unknown';
        const snap = s.snapshot_url || '/static/avatar-placeholder.png';
        const name = s.entity_name || 'Unidentified Track';
        const cat = s.entity_category || 'person';
        const confPct = s.confidence ? (s.confidence * 100).toFixed(0) : '100';

        return `
          <div class="timeline-node">
            <div class="timeline-dot"></div>
            <div class="glass-panel timeline-card">
              <img class="timeline-thumbnail" src="${snap}" onerror="this.style.display='none'" alt="Snapshot" onclick="window.showSnapshotModal('${snap}', '${escapeHtml(name)} - ${escapeHtml(timeStr)}')" />
              <div class="timeline-content">
                <div class="timeline-title">
                  <span>${escapeHtml(name)}</span>
                  <span class="badge-category ${cat}">${cat}</span>
                  <span class="panel-badge">Zone: ${escapeHtml(s.zone_id || 'Free space')}</span>
                </div>
                <div class="timeline-meta">
                  <span>🕒 ${escapeHtml(timeStr)}</span> &bull;
                  <span>Track #${s.track_id}</span> &bull;
                  <span>Match Confidence: ${confPct}%</span>
                </div>
              </div>
            </div>
          </div>
        `;
      }).join('');
    } catch (err) {
      timelineList.innerHTML = `<div class="empty-state">Error querying sightings: ${escapeHtml(err.message)}</div>`;
    }
  }

  // Global snapshot modal viewer
  window.showSnapshotModal = (imgUrl, title) => {
    if (!modalSnapshot || !modalSnapshotImg || !modalSnapshotMeta) return;
    modalSnapshotImg.src = imgUrl;
    modalSnapshotMeta.textContent = title;
    modalSnapshot.style.display = 'flex';
  };

  function initTimeline() {
    btnFilterSightings?.addEventListener('click', loadSightings);
    modalSnapshotClose?.addEventListener('click', () => {
      if (modalSnapshot) modalSnapshot.style.display = 'none';
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTimeline);
  } else {
    initTimeline();
  }

  window.TrackerApp.Timeline = {
    loadFilters: loadTimelineFilters,
    loadSightings: loadSightings,
  };
})();

