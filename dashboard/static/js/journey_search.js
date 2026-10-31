/**
 * Intelligent Tracker - Trajectory Journey Search & Video Export Submodule.
 * Handles cross-camera hop reconstruction, summary narratives, and MP4 video generation.
 */

(function () {
  'use strict';

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderHopCards(hops) {
    return hops.map((hop) => {
      const startTimeStr = new Date(hop.start_time * 1000).toLocaleTimeString();
      const transitBadge = hop.transit_time_from_prev
        ? `<div class="transit-connector"><span>⏱️ Transit: +${hop.transit_time_from_prev}s</span></div>`
        : '';
      const thumbUrl = hop.snapshot_path ? `/crops/${hop.snapshot_path.split(/[\\/]/).pop()}` : '';

      return `
        ${transitBadge}
        <div class="hop-card glass-panel">
          <div class="hop-num">#${hop.hop_index}</div>
          <div class="hop-details">
            <div class="hop-title">
              <strong>${escapeHtml(hop.camera_name)}</strong>
              <span class="hop-time">${startTimeStr}</span>
            </div>
            <div class="hop-meta">
              <span>Zone: ${escapeHtml(hop.zone_id || 'General Area')}</span> •
              <span>Dwell: ${hop.duration_seconds}s</span> •
              <span>Sightings: ${hop.sightings_count}</span>
            </div>
          </div>
          ${thumbUrl ? `<div class="hop-thumb"><img src="${thumbUrl}" alt="Snapshot" /></div>` : ''}
        </div>
      `;
    }).join('');
  }

  function renderJourneyResults(journey) {
    const container = document.getElementById('journey-results-container');
    if (!container) return;

    if (!journey.hops || journey.hops.length === 0) {
      container.innerHTML = '<div class="empty-state">No camera transitions detected for this entity.</div>';
      return;
    }

    container.innerHTML = `
      <div class="journey-summary-card glass-panel">
        <div class="journey-header">
          <h4>🚶 Trajectory Journey: <strong>${escapeHtml(journey.entity_name)}</strong> (${escapeHtml(journey.category.toUpperCase())})</h4>
          <span class="badge ${journey.total_hops > 1 ? 'badge-primary' : 'badge-secondary'}">${journey.total_hops} Hops | ${journey.total_duration_seconds}s</span>
        </div>
        <div class="journey-narrative">${escapeHtml(journey.summary_narrative)}</div>
      </div>
      <div class="journey-hops-timeline">
        ${renderHopCards(journey.hops)}
      </div>
    `;
  }

  async function searchJourney(entityNameOrId) {
    const container = document.getElementById('journey-results-container');
    if (!container) return;

    container.innerHTML = '<div class="loading-state">🔍 Reconstructing cross-camera trajectory journey...</div>';

    try {
      const param = isNaN(entityNameOrId) ? `entity_name=${encodeURIComponent(entityNameOrId)}` : `entity_id=${entityNameOrId}`;
      const res = await fetch(`/api/journey/search?${param}`);
      if (!res.ok) {
        container.innerHTML = '<div class="empty-state">No journey sightings found for this entity.</div>';
        return;
      }

      const journey = await res.json();
      renderJourneyResults(journey);
    } catch (err) {
      container.innerHTML = `<div class="error-state">Error searching journey: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function exportJourneyVideo(entityNameOrId) {
    const btn = document.getElementById('btn-journey-export');
    const statusDiv = document.getElementById('journey-export-status');
    if (btn) btn.disabled = true;
    if (statusDiv) statusDiv.innerHTML = '⏳ Slicing footage and concatenating MP4 video with tactical HUD title cards...';

    try {
      const payload = isNaN(entityNameOrId) ? { entity_name: entityNameOrId } : { entity_id: parseInt(entityNameOrId, 10) };
      const res = await fetch('/api/journey/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Export failed');
      }

      const data = await res.json();
      if (statusDiv) {
        statusDiv.innerHTML = `
          <div class="alert alert-success">
            ✅ <strong>Journey MP4 Ready!</strong>
            <a href="${data.video_url}" target="_blank" class="btn btn-sm btn-primary" download>⬇️ Download MP4 (${escapeHtml(data.video_file)})</a>
            <div class="video-preview-box" style="margin-top: 10px;">
              <video src="${data.video_url}" controls autoplay style="max-width: 100%; border-radius: 6px;"></video>
            </div>
          </div>
        `;
      }
    } catch (err) {
      if (statusDiv) statusDiv.innerHTML = `<div class="alert alert-danger">❌ Export failed: ${escapeHtml(err.message)}</div>`;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function bindJourneySearch() {
    const btnSearch = document.getElementById('btn-journey-search');
    const btnExport = document.getElementById('btn-journey-export');

    if (btnSearch) {
      btnSearch.addEventListener('click', () => {
        const query = (document.getElementById('journey-search-query')?.value || '').trim();
        searchJourney(query);
      });
    }

    if (btnExport) {
      btnExport.addEventListener('click', () => {
        const query = (document.getElementById('journey-search-query')?.value || '').trim();
        exportJourneyVideo(query);
      });
    }
  }

  window.JourneySearch = {
    bind: bindJourneySearch,
    search: searchJourney,
    exportVideo: exportJourneyVideo,
  };
})();

