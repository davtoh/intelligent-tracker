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

  function handleThumbError(imgEl) {
    if (!imgEl) return;
    imgEl.onerror = null;
    if (window.MediaEmptyState?.showEmpty) {
      window.MediaEmptyState.showEmpty(imgEl, 'Snapshot Unavailable', 'Crop could not be loaded.', true);
    } else {
      imgEl.src = '/static/avatar-placeholder.svg';
    }
  }

  function renderHopCards(hops) {
    return hops.map((hop) => {
      const startTimeStr = new Date(hop.start_time * 1000).toLocaleTimeString();
      const transitBadge = hop.transit_time_from_prev
        ? `<div class="transit-connector"><span>⏱️ Transit: +${hop.transit_time_from_prev}s</span></div>`
        : '';
      const thumbUrl = hop.snapshot_url || (hop.snapshot_path ? `/crops/${encodeURIComponent(hop.snapshot_path.split(/[\\/]/).pop())}` : '');
      const seekBtn = window.VideoTimelineLinks?.buildSeekInStudioButtonHtml(hop.video_filename, hop.media_offset_sec) || '';
      const hopRef = hop.source_ref && Object.keys(hop.source_ref).length ? hop.source_ref : {
        cameraId: hop.camera_id, videoFilename: hop.video_filename, runId: hop.run_id,
        mediaOffsetSec: hop.media_offset_sec, zoneId: hop.zone_id, trackId: hop.track_id,
      };
      const jumpBtns = window.VideoTimelineLinks?.buildSourceJumpButtonsHtml?.(hopRef, { includeVideo: false }) || '';
      const trackBadge = hop.track_id !== undefined && hop.track_id !== null && hop.track_id !== ''
        ? `<span class="badge badge-secondary hop-track-badge">Track #${escapeHtml(hop.track_id)}</span>`
        : '';

      return `
        ${transitBadge}
        <div class="hop-card glass-panel">
          <div class="hop-num">#${hop.hop_index}</div>
          <div class="hop-details">
            <div class="hop-title">
              <strong>${escapeHtml(hop.camera_name)}</strong>
              ${trackBadge}
              <span class="hop-time">${startTimeStr}</span>
            </div>
            <div class="hop-meta">
              <span>Zone: ${escapeHtml(hop.zone_id || 'General Area')}</span> •
              <span>Dwell: ${hop.duration_seconds}s</span> •
              <span>Sightings: ${hop.sightings_count}</span>
              ${seekBtn} ${jumpBtns}
            </div>
          </div>
          ${thumbUrl ? `<div class="hop-thumb"><img src="${thumbUrl}" alt="Snapshot" onerror="window.JourneySearch?.handleThumbError?.(this)" /></div>` : ''}
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
    const q = String(entityNameOrId ?? '').trim();
    if (!q) {
      container.innerHTML = '<div class="empty-state">Enter an entity name or numeric Track ID to search.</div>';
      return;
    }

    container.innerHTML = '<div class="loading-state">🔍 Reconstructing cross-camera trajectory journey...</div>';

    try {
      const param = /^\d+$/.test(q) ? `track_id=${encodeURIComponent(q)}` : `entity_name=${encodeURIComponent(q)}`;
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
    const q = String(entityNameOrId ?? '').trim();
    if (!q) {
      if (statusDiv) statusDiv.innerHTML = '<div class="alert alert-danger">Enter an entity name or numeric Track ID first.</div>';
      return;
    }
    if (btn) btn.disabled = true;
    if (statusDiv) statusDiv.innerHTML = '⏳ Slicing footage and concatenating MP4 video with tactical HUD title cards...';

    try {
      const payload = /^\d+$/.test(q) ? { track_id: parseInt(q, 10) } : { entity_name: q };
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

  let suggestTimer = null;
  let suggestItems = [];
  let activeSuggestIndex = -1;
  let outsideDismissBound = false;

  function hideSuggestions() {
    const list = document.getElementById('journey-suggest-list');
    if (list) {
      list.innerHTML = '';
      list.classList.add('hidden');
    }
    suggestItems = [];
    activeSuggestIndex = -1;
  }

  function renderSuggestions(items) {
    const list = document.getElementById('journey-suggest-list');
    if (!list) return;
    suggestItems = Array.isArray(items) ? items : [];
    activeSuggestIndex = -1;
    if (suggestItems.length === 0) {
      hideSuggestions();
      return;
    }
    list.innerHTML = suggestItems.map((item, idx) => `
      <li class="journey-suggest-item" role="option" data-index="${idx}" data-name="${escapeHtml(item.name || '')}">
        <span class="suggest-name">${escapeHtml(item.name || '')}</span>
        <span class="suggest-meta">#${escapeHtml(item.id)} · ${escapeHtml(item.category || 'person')}</span>
      </li>
    `).join('');
    list.classList.remove('hidden');
  }

  function highlightSuggestion(nextIndex) {
    const list = document.getElementById('journey-suggest-list');
    if (!list || suggestItems.length === 0) return;
    activeSuggestIndex = Math.max(-1, Math.min(nextIndex, suggestItems.length - 1));
    Array.from(list.children).forEach((el, idx) => {
      if (idx === activeSuggestIndex) el.classList.add('active');
      else el.classList.remove('active');
    });
  }

  async function fetchSuggestions(query = '') {
    const trimmed = String(query ?? '').trim();
    try {
      const res = await fetch(`/api/entities/suggest?q=${encodeURIComponent(trimmed)}&limit=8`);
      if (!res.ok) {
        hideSuggestions();
        return [];
      }
      const data = await res.json();
      const items = Array.isArray(data?.items) ? data.items : [];
      renderSuggestions(items);
      return items;
    } catch (_err) {
      hideSuggestions();
      return [];
    }
  }

  function selectSuggestion(index) {
    const item = suggestItems[index];
    if (!item) return;
    const input = document.getElementById('journey-search-query');
    if (input) input.value = item.name || String(item.id || '');
    hideSuggestions();
    searchJourney(input?.value || item.name);
  }

  function bindOutsideDismiss() {
    if (outsideDismissBound || typeof document?.addEventListener !== 'function') return;
    outsideDismissBound = true;
    document.addEventListener('pointerdown', (e) => {
      const target = e?.target;
      const input = document.getElementById('journey-search-query');
      const list = document.getElementById('journey-suggest-list');
      const inInput = input && (target === input || (typeof input.contains === 'function' && input.contains(target)));
      const inList = list && (target === list || (typeof list.contains === 'function' && list.contains(target)));
      if (!inInput && !inList) hideSuggestions();
    });
  }

  function bindJourneySearch() {
    const btnSearch = document.getElementById('btn-journey-search');
    const btnExport = document.getElementById('btn-journey-export');
    const input = document.getElementById('journey-search-query');
    const list = document.getElementById('journey-suggest-list');

    if (btnSearch) {
      btnSearch.addEventListener('click', () => {
        hideSuggestions();
        searchJourney((input?.value || '').trim());
      });
    }

    if (btnExport) {
      btnExport.addEventListener('click', () => {
        hideSuggestions();
        exportJourneyVideo((input?.value || '').trim());
      });
    }

    if (input) {
      const triggerOpen = () => fetchSuggestions(input.value || '');
      input.addEventListener('focus', triggerOpen);
      input.addEventListener('click', triggerOpen);
      input.addEventListener('input', () => {
        if (suggestTimer) ((id) => clearTimeout(id))(suggestTimer);
        suggestTimer = ((fn, ms) => setTimeout(fn, ms))(() => fetchSuggestions(input.value), 180);
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          highlightSuggestion(activeSuggestIndex + 1);
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          highlightSuggestion(activeSuggestIndex - 1);
        } else if (e.key === 'Escape') {
          hideSuggestions();
        } else if (e.key === 'Enter') {
          e.preventDefault();
          if (activeSuggestIndex >= 0 && suggestItems[activeSuggestIndex]) {
            selectSuggestion(activeSuggestIndex);
          } else {
            hideSuggestions();
            searchJourney((input.value || '').trim());
          }
        }
      });
    }

    if (list) {
      list.addEventListener('click', (e) => {
        const li = e.target?.closest ? e.target.closest('.journey-suggest-item') : null;
        if (!li) return;
        const idx = Number(li.dataset?.index ?? -1);
        if (idx >= 0) selectSuggestion(idx);
      });
    }
    bindOutsideDismiss();
  }

  window.JourneySearch = {
    bind: bindJourneySearch,
    search: searchJourney,
    exportVideo: exportJourneyVideo,
    fetchSuggestions,
    hideSuggestions,
    handleThumbError,
  };
})();

