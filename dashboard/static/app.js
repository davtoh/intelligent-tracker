/**
 * Intelligent Tracker Web Dashboard - Client-side Controller.
 * Handles WebSocket telemetry stream, interactive click-to-tag canvas,
 * entity gallery management, sighting timeline search, and Chart.js analytics.
 */

document.addEventListener('DOMContentLoaded', () => {
  // Application State
  const state = {
    activeTab: 'tab-live',
    wsConnected: false,
    ws: null,
    latestTelemetry: null,
    tracks: [],
    hoveredTrack: null,
    heatmapActive: false,
    chart: null,
    trafficData: { labels: [], inFlow: [], outFlow: [] },
  };

  // DOM Elements
  const headerFps = document.getElementById('header-fps-val');
  const connStatusPill = document.getElementById('connection-status-pill');
  const connStatusText = document.getElementById('connection-status-text');
  const alertBadge = document.getElementById('header-alert-badge');

  // Video & Canvas
  const videoImg = document.getElementById('live-stream-img');
  const canvas = document.getElementById('interactive-canvas');
  const ctx = canvas.getContext('2d');
  const trackTooltip = document.getElementById('track-tooltip');
  const tooltipTitle = document.getElementById('tooltip-title');
  const tooltipBody = document.getElementById('tooltip-body');
  const tooltipTagBtn = document.getElementById('tooltip-tag-btn');
  const toggleHeatmapBtn = document.getElementById('toggle-heatmap-btn');

  // KPIs
  const kpiActiveTracks = document.getElementById('kpi-active-tracks');
  const kpiTotalCrossed = document.getElementById('kpi-total-crossed');
  const zonesContainer = document.getElementById('zones-container');
  const tripwiresContainer = document.getElementById('tripwires-container');
  const liveAlertsFeed = document.getElementById('live-alerts-feed');

  // Gallery
  const galleryGrid = document.getElementById('entity-gallery-grid');
  const gallerySearch = document.getElementById('gallery-search-input');
  const galleryCategoryFilters = document.getElementById('gallery-category-filters');

  // Timeline
  const timelineSelectEntity = document.getElementById('timeline-entity-select');
  const timelineSelectZone = document.getElementById('timeline-zone-select');
  const timelineSelectLimit = document.getElementById('timeline-limit-select');
  const timelineList = document.getElementById('sightings-timeline-list');
  const btnFilterSightings = document.getElementById('btn-filter-sightings');

  // Modals
  const modalTag = document.getElementById('modal-tag-entity');
  const tagForm = document.getElementById('tag-entity-form');
  const tagTrackId = document.getElementById('tag-track-id');
  const tagBboxVal = document.getElementById('tag-bbox-val');
  const tagNameInput = document.getElementById('tag-name-input');
  const tagCategorySelect = document.getElementById('tag-category-select');
  const tagNotesInput = document.getElementById('tag-notes-input');
  const modalTagClose = document.getElementById('modal-tag-close');
  const modalTagCancel = document.getElementById('modal-tag-cancel');

  const modalSnapshot = document.getElementById('modal-snapshot-view');
  const modalSnapshotImg = document.getElementById('snapshot-modal-img');
  const modalSnapshotMeta = document.getElementById('snapshot-modal-meta');
  const modalSnapshotClose = document.getElementById('modal-snapshot-close');

  // =========================================================================
  // Tab Navigation
  // =========================================================================
  const navTabs = document.querySelectorAll('.nav-tab');
  const tabPanes = document.querySelectorAll('.tab-pane');

  function switchTab(targetTabId) {
    const previousTab = state.activeTab;
    state.activeTab = targetTabId;
    navTabs.forEach(tab => {
      const isTarget = tab.getAttribute('data-tab') === targetTabId;
      tab.classList.toggle('active', isTarget);
    });
    tabPanes.forEach(pane => {
      pane.classList.toggle('active', pane.id === targetTabId);
    });

    // Resource Hibernation: Handle leaving previous tab
    if (previousTab === 'tab-videos' && targetTabId !== 'tab-videos') {
      if (window.VideoScrubber && typeof window.VideoScrubber.onTabLeave === 'function') {
        window.VideoScrubber.onTabLeave();
      }
    } else if (previousTab === 'tab-live' && targetTabId !== 'tab-live') {
      if (videoImg && videoImg.src) {
        videoImg.dataset.activeStreamSrc = videoImg.src;
        videoImg.src = '';
      }
    }

    // Resource Activation: Handle entering target tab
    if (targetTabId === 'tab-live') {
      if (videoImg && videoImg.dataset.activeStreamSrc && !videoImg.src) {
        videoImg.src = videoImg.dataset.activeStreamSrc;
      }
    } else if (targetTabId === 'tab-videos') {
      if (window.VideoScrubber) {
        window.VideoScrubber.loadVideosList();
        if (typeof window.VideoScrubber.onTabEnter === 'function') {
          window.VideoScrubber.onTabEnter();
        }
      }
    } else if (targetTabId === 'tab-gallery') {
      loadGallery();
    } else if (targetTabId === 'tab-timeline') {
      loadTimelineFilters();
      loadSightings();
    } else if (targetTabId === 'tab-analytics') {
      initTrafficChart();
    } else if (targetTabId === 'tab-alerts') {
      loadAlertsTable();
    } else if (targetTabId === 'tab-studio') {
      if (window.Studio) window.Studio.renderBEV();
    } else if (targetTabId === 'tab-journey') {
      // Focus search input
      document.getElementById('journey-search-query')?.focus();
    } else if (targetTabId === 'tab-review') {
      if (window.ReviewAndRSAC) window.ReviewAndRSAC.loadQueue('pending');
    }
  }

  // Page Visibility API support: pause/resume when window or browser tab is hidden/restored
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      if (state.activeTab === 'tab-videos' && window.VideoScrubber) {
        window.VideoScrubber.onTabLeave();
      }
    } else {
      if (state.activeTab === 'tab-videos' && window.VideoScrubber) {
        window.VideoScrubber.onTabEnter();
      }
    }
  });

  navTabs.forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.getAttribute('data-tab')));
  });

  document.getElementById('view-all-alerts-link')?.addEventListener('click', () => {
    switchTab('tab-alerts');
  });

  // Backup Modal bindings
  const modalBackup = document.getElementById('modal-backup-manager');
  const btnBackupOpen = document.getElementById('btn-backup-manager');
  const btnBackupClose = document.getElementById('modal-backup-close');
  const btnImportBackup = document.getElementById('btn-import-backup-file');
  const backupFileInput = document.getElementById('backup-file-input');
  const backupImportStatus = document.getElementById('backup-import-status');

  if (btnBackupOpen && modalBackup) {
    btnBackupOpen.addEventListener('click', () => {
      modalBackup.style.display = 'flex';
    });
  }
  if (btnBackupClose && modalBackup) {
    btnBackupClose.addEventListener('click', () => {
      modalBackup.style.display = 'none';
    });
  }
  if (modalBackup) {
    modalBackup.addEventListener('click', (e) => {
      if (e.target === modalBackup) modalBackup.style.display = 'none';
    });
  }

  if (btnImportBackup && backupFileInput) {
    btnImportBackup.addEventListener('click', () => backupFileInput.click());
    backupFileInput.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      if (!confirm(`Import and restore full system state from '${file.name}'? Existing database records will be backed up.`)) {
        backupFileInput.value = '';
        return;
      }
      const formData = new FormData();
      formData.append('file', file);
      backupImportStatus.innerHTML = '<span style="color:#06b6d4;">Restoring system snapshot...</span>';

      try {
        const resp = await fetch('/api/backup/import', {
          method: 'POST',
          body: formData,
        });
        if (resp.ok) {
          const res = await resp.json();
          backupImportStatus.innerHTML = `<span style="color:#10b981;">✓ Successfully restored ${res.details.restored_files_count} files!</span>`;
          setTimeout(() => {
            alert('System snapshot restored successfully! Reloading dashboard...');
            window.location.reload();
          }, 1200);
        } else {
          const err = await resp.json();
          backupImportStatus.innerHTML = `<span style="color:#ef4444;">✗ Restore failed: ${err.detail || 'Error'}</span>`;
        }
      } catch (err) {
        backupImportStatus.innerHTML = `<span style="color:#ef4444;">✗ Network error: ${err.message}</span>`;
      } finally {
        backupFileInput.value = '';
      }
    });
  }

  // =========================================================================
  // WebSocket Connection
  let activeCameraId = 'cam_01';
  let wsReconnectTimer = null;

  // =========================================================================
  // WebSocket Connection & Telemetry Gateway
  // =========================================================================
  function initWebSocket(camId) {
    if (camId) activeCameraId = camId;
    if (wsReconnectTimer) {
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = null;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${encodeURIComponent(activeCameraId)}`;

    if (state.ws) {
      state.ws.onclose = null;
      state.ws.onerror = null;
      try { state.ws.close(); } catch (e) {}
    }

    try {
      state.ws = new WebSocket(wsUrl);
    } catch (e) {
      console.warn('WebSocket init error:', e);
      return;
    }

    state.ws.onopen = () => {
      state.wsConnected = true;
      connStatusPill.className = 'connection-status-pill online';
      connStatusText.textContent = `Connected (${activeCameraId})`;
    };

    state.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleTelemetry(data);
      } catch (err) {
        console.error('WS parse error:', err);
      }
    };

    state.ws.onclose = () => {
      state.wsConnected = false;
      connStatusPill.className = 'connection-status-pill offline';
      connStatusText.textContent = 'Reconnecting...';
      wsReconnectTimer = setTimeout(() => initWebSocket(activeCameraId), 2000);
    };

    state.ws.onerror = () => {
      state.ws?.close();
    };
  }

  function switchCamera(camId) {
    if (!camId || camId === activeCameraId) return;
    activeCameraId = camId;
    initWebSocket(camId);
  }

  // =========================================================================
  // Telemetry Processing
  // =========================================================================
  function handleTelemetry(data) {
    state.latestTelemetry = data;
    state.tracks = data.active_tracks || [];

    // Header FPS
    if (data.fps !== undefined) {
      headerFps.textContent = data.fps.toFixed(1);
    }

    // Update Stream Resolution Badge if present
    const resBadge = document.getElementById('stream-res-badge');
    if (resBadge && data.resolution) {
      resBadge.textContent = data.resolution;
    }

    // Active Tracks Count
    if (kpiActiveTracks) {
      kpiActiveTracks.textContent = state.tracks.length;
    }

    // Zones
    if (data.zones && zonesContainer) {
      renderZones(data.zones);
    }

    // Tripwires
    let totalCrossed = 0;
    if (data.tripwires && tripwiresContainer) {
      renderTripwires(data.tripwires);
      data.tripwires.forEach(tw => { totalCrossed += (tw.in_count + tw.out_count); });
      if (kpiTotalCrossed) kpiTotalCrossed.textContent = totalCrossed;
      updateTrafficChart(totalCrossed);
    }

    // Recent Alerts Mini Feed & Milestone 9 Toast Dispatcher
    if (data.recent_alerts && liveAlertsFeed) {
      renderMiniAlerts(data.recent_alerts);
      if (alertBadge) alertBadge.textContent = data.recent_alerts.length;
      if (window.ReviewAndRSAC && typeof window.ReviewAndRSAC.checkAlertEvents === 'function') {
        window.ReviewAndRSAC.checkAlertEvents(data.recent_alerts);
      }
    }

    // Update Interactive Canvas
    syncCanvasSize();
    drawInteractiveOverlay();
  }

  function renderZones(zones) {
    if (!zones.length) {
      zonesContainer.innerHTML = '<div class="empty-state">No zones defined</div>';
      return;
    }
    document.getElementById('zone-count-badge').textContent = `${zones.length} zone${zones.length > 1 ? 's' : ''}`;
    zonesContainer.innerHTML = zones.map(z => {
      const cap = z.capacity_limit || 10;
      const pct = Math.min(100, Math.round((z.occupancy / cap) * 100));
      let statusClass = '';
      let barClass = '';
      if (z.is_breached || (z.capacity_limit && z.occupancy >= z.capacity_limit)) {
        statusClass = 'breached';
        barClass = 'danger';
      } else if (pct > 75) {
        barClass = 'warning';
      }
      return `
        <div class="zone-item ${statusClass}">
          <div class="zone-info">
            <span>${escapeHtml(z.name)}</span>
            <span>${z.occupancy} ${z.capacity_limit ? '/ ' + z.capacity_limit : ''}</span>
          </div>
          <div class="zone-progress-bg">
            <div class="zone-progress-bar ${barClass}" style="width: ${pct}%"></div>
          </div>
        </div>
      `;
    }).join('');
  }

  function renderTripwires(tripwires) {
    if (!tripwires.length) {
      tripwiresContainer.innerHTML = '<div class="empty-state">No tripwires defined</div>';
      return;
    }
    tripwiresContainer.innerHTML = tripwires.map(tw => `
      <div class="tripwire-item">
        <span>${escapeHtml(tw.name)}</span>
        <div class="tw-counts">
          <span class="tw-in">IN: ${tw.in_count}</span>
          <span class="tw-out">OUT: ${tw.out_count}</span>
        </div>
      </div>
    `).join('');
  }

  function renderMiniAlerts(alerts) {
    if (!alerts.length) {
      liveAlertsFeed.innerHTML = '<div class="empty-state">No active security alerts</div>';
      return;
    }
    liveAlertsFeed.innerHTML = alerts.slice(0, 5).map(a => {
      const type = a.event_type || 'alert';
      const isDanger = type.includes('intrusion') || type.includes('restricted') || type.includes('breach');
      const timeStr = a.timestamp ? new Date(a.timestamp * 1000).toLocaleTimeString() : '--:--';
      return `
        <div class="alert-mini-card ${isDanger ? 'intrusion' : ''}">
          <div class="alert-mini-header">
            <span>${escapeHtml(type.toUpperCase())}</span>
            <span class="alert-mini-time">${timeStr}</span>
          </div>
          <div class="alert-mini-sub">${escapeHtml(a.entity_name || a.zone_id || 'Security event')}</div>
        </div>
      `;
    }).join('');
  }

  // =========================================================================
  // Interactive Click-to-Tag Overlay Canvas
  // =========================================================================
  function syncCanvasSize() {
    if (videoImg.clientWidth && videoImg.clientHeight) {
      if (canvas.width !== videoImg.clientWidth || canvas.height !== videoImg.clientHeight) {
        canvas.width = videoImg.clientWidth;
        canvas.height = videoImg.clientHeight;
      }
      canvas.style.top = videoImg.offsetTop + 'px';
      canvas.style.left = videoImg.offsetLeft + 'px';
      canvas.style.width = videoImg.clientWidth + 'px';
      canvas.style.height = videoImg.clientHeight + 'px';
    }
  }

  function drawInteractiveOverlay() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!videoImg.naturalWidth || !canvas.width) return;

    const scaleX = canvas.width / videoImg.naturalWidth;
    const scaleY = canvas.height / videoImg.naturalHeight;

    state.tracks.forEach(trk => {
      const [bx, by, bw, bh] = trk.bbox;
      const x = bx * scaleX;
      const y = by * scaleY;
      const w = bw * scaleX;
      const h = bh * scaleY;

      const isHovered = state.hoveredTrack && state.hoveredTrack.id === trk.id;

      if (isHovered) {
        // High-tech glowing cyan border for selected/hovered entity
        ctx.strokeStyle = '#06b6d4';
        ctx.lineWidth = 3;
        ctx.shadowColor = '#06b6d4';
        ctx.shadowBlur = 12;
        ctx.strokeRect(x, y, w, h);
        ctx.shadowBlur = 0;

        // Semi-transparent highlight fill
        ctx.fillStyle = 'rgba(6, 182, 212, 0.12)';
        ctx.fillRect(x, y, w, h);
      }
    });
  }

  // Canvas Mouse Interaction for Click-to-Tag
  canvas.addEventListener('mousemove', (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    if (!videoImg.naturalWidth) return;
    const scaleX = canvas.width / videoImg.naturalWidth;
    const scaleY = canvas.height / videoImg.naturalHeight;

    let found = null;
    for (const trk of state.tracks) {
      const [bx, by, bw, bh] = trk.bbox;
      const x = bx * scaleX;
      const y = by * scaleY;
      const w = bw * scaleX;
      const h = bh * scaleY;

      if (mx >= x && mx <= x + w && my >= y && my <= y + h) {
        found = trk;
        break;
      }
    }

    state.hoveredTrack = found;
    drawInteractiveOverlay();

    if (found) {
      const [bx, by, bw, bh] = found.bbox;
      const x = bx * scaleX;
      const y = by * scaleY;

      trackTooltip.style.display = 'block';
      trackTooltip.style.left = `${Math.min(canvas.width - 180, Math.max(10, x))}px`;
      trackTooltip.style.top = `${Math.max(10, y - 70)}px`;

      tooltipTitle.textContent = found.entity_name || `Track #${found.id}`;
      tooltipBody.textContent = `Conf: ${(found.confidence * 100).toFixed(0)}% | Dwell: ${found.dwell_time}s | State: ${found.state}`;
    } else {
      trackTooltip.style.display = 'none';
    }
  });

  canvas.addEventListener('mouseleave', () => {
    state.hoveredTrack = null;
    trackTooltip.style.display = 'none';
    drawInteractiveOverlay();
  });

  canvas.addEventListener('click', (e) => {
    if (state.hoveredTrack) {
      openTagModal(state.hoveredTrack);
    }
  });

  tooltipTagBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (state.hoveredTrack) {
      openTagModal(state.hoveredTrack);
    }
  });

  document.getElementById('btn-quick-tag')?.addEventListener('click', () => {
    if (state.tracks.length > 0) {
      openTagModal(state.tracks[0]);
    } else {
      openTagModal(null);
    }
  });

  // =========================================================================
  // Click-to-Tag Modal
  // =========================================================================
  function openTagModal(track) {
    modalTag.style.display = 'flex';
    if (track) {
      tagTrackId.value = track.id;
      tagBboxVal.value = JSON.stringify(track.bbox);
      tagNameInput.value = track.entity_name || '';
      tagCategorySelect.value = track.category || 'person';
      document.getElementById('tag-modal-title').textContent = `🏷️ Tag Active Track #${track.id}`;
    } else {
      tagTrackId.value = '';
      tagBboxVal.value = '';
      tagNameInput.value = '';
      tagCategorySelect.value = 'person';
      document.getElementById('tag-modal-title').textContent = '🏷️ Enroll New Identity';
    }
    tagNameInput.focus();
  }

  function closeTagModal() {
    modalTag.style.display = 'none';
    tagForm.reset();
  }

  modalTagClose.addEventListener('click', closeTagModal);
  modalTagCancel.addEventListener('click', closeTagModal);

  tagForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = tagNameInput.value.trim();
    const category = tagCategorySelect.value;
    const notes = tagNotesInput.value.trim();
    const trackId = tagTrackId.value ? parseInt(tagTrackId.value, 10) : null;
    const bbox = tagBboxVal.value ? JSON.parse(tagBboxVal.value) : null;

    if (!name) return;

    try {
      const res = await fetch('/tag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entity_name: name,
          category: category,
          track_id: trackId,
          bbox: bbox,
          notes: notes,
          camera_id: activeCameraId || 'cam_01',
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Tagging failed');
      }

      closeTagModal();
      // Show notification toast
      alert(`Successfully enrolled "${name}" as ${category.toUpperCase()} into the Re-ID Gallery!`);
    } catch (err) {
      alert(`Error enrolling entity: ${err.message}`);
    }
  });

  // =========================================================================
  // Heatmap Toggle Button
  // =========================================================================
  toggleHeatmapBtn?.addEventListener('click', async () => {
    try {
      const res = await fetch('/analytics/heatmap/toggle', { method: 'POST' });
      const data = await res.json();
      state.heatmapActive = data.draw_heatmap;
      toggleHeatmapBtn.textContent = state.heatmapActive ? '🔥 Heatmap: ON' : '🔥 Heatmap: OFF';
      toggleHeatmapBtn.classList.toggle('active', state.heatmapActive);
    } catch (err) {
      console.error('Heatmap toggle error:', err);
    }
  });

  // Fullscreen Button
  document.getElementById('fullscreen-btn')?.addEventListener('click', () => {
    const wrapper = document.getElementById('video-wrapper');
    if (!document.fullscreenElement) {
      wrapper.requestFullscreen().catch(err => console.error(err));
    } else {
      document.exitFullscreen();
    }
  });

  // Save Snapshot Button
  document.getElementById('btn-snapshot-save')?.addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = `/stream/cam_01`;
    a.download = `snapshot_${Date.now()}.jpg`;
    window.open(`/stream/cam_01`, '_blank');
  });

  // =========================================================================
  // Tab 2: Entity Gallery View
  // =========================================================================
  let allGalleryEntities = [];

  async function loadGallery() {
    try {
      const res = await fetch('/entities');
      allGalleryEntities = await res.json();
      renderGalleryGrid();
    } catch (err) {
      galleryGrid.innerHTML = `<div class="empty-state">Error loading gallery: ${err.message}</div>`;
    }
  }

  function renderGalleryGrid() {
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
        switchTab('tab-timeline');
        timelineSelectEntity.value = entId;
        loadSightings();
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

  gallerySearch?.addEventListener('input', renderGalleryGrid);
  galleryCategoryFilters?.querySelectorAll('.filter-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      galleryCategoryFilters.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      renderGalleryGrid();
    });
  });

  document.getElementById('btn-enroll-modal')?.addEventListener('click', () => openTagModal(null));

  // =========================================================================
  // Tab 3: Sighting Timeline Player
  // =========================================================================
  async function loadTimelineFilters() {
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
    const entId = timelineSelectEntity.value;
    const zoneId = timelineSelectZone.value;
    const limit = timelineSelectLimit.value || 50;

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
              <img class="timeline-thumbnail" src="${snap}" onerror="this.style.display='none'" alt="Snapshot" onclick="showSnapshotModal('${snap}', '${escapeHtml(name)} - ${escapeHtml(timeStr)}')" />
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
      timelineList.innerHTML = `<div class="empty-state">Error querying sightings: ${err.message}</div>`;
    }
  }

  btnFilterSightings?.addEventListener('click', loadSightings);

  // Snapshot modal viewer
  window.showSnapshotModal = (imgUrl, title) => {
    modalSnapshotImg.src = imgUrl;
    modalSnapshotMeta.textContent = title;
    modalSnapshot.style.display = 'flex';
  };

  modalSnapshotClose?.addEventListener('click', () => {
    modalSnapshot.style.display = 'none';
  });

  // =========================================================================
  // Tab 4: Analytics Chart & Heatmap
  // =========================================================================
  function initTrafficChart() {
    if (state.chart) return;
    const chartCanvas = document.getElementById('trafficChart');
    if (!chartCanvas) return;

    const ctxChart = chartCanvas.getContext('2d');
    state.chart = new Chart(ctxChart, {
      type: 'line',
      data: {
        labels: ['-30s', '-25s', '-20s', '-15s', '-10s', '-5s', 'Now'],
        datasets: [
          {
            label: 'Tripwire Inflow',
            data: [0, 1, 2, 2, 4, 5, 7],
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            fill: true,
            tension: 0.35,
          },
          {
            label: 'Tripwire Outflow',
            data: [0, 0, 1, 1, 2, 3, 4],
            borderColor: '#f59e0b',
            backgroundColor: 'rgba(245, 158, 11, 0.1)',
            fill: true,
            tension: 0.35,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#94a3b8', font: { family: 'Inter' } } }
        },
        scales: {
          x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' } },
          y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' }, beginAtZero: true }
        }
      }
    });
  }

  function updateTrafficChart(totalCount) {
    if (!state.chart) return;
    const nowLabel = new Date().toLocaleTimeString();
    if (state.chart.data.labels.length > 15) {
      state.chart.data.labels.shift();
      state.chart.data.datasets[0].data.shift();
      state.chart.data.datasets[1].data.shift();
    }
    state.chart.data.labels.push(nowLabel);
    state.chart.data.datasets[0].data.push(Math.round(totalCount * 0.6));
    state.chart.data.datasets[1].data.push(Math.round(totalCount * 0.4));
    state.chart.update('none');
  }

  document.getElementById('btn-refresh-heatmap')?.addEventListener('click', () => {
    const img = document.getElementById('static-heatmap-img');
    if (img) img.src = `/analytics/heatmap?t=${Date.now()}`;
  });

  // =========================================================================
  // Tab 5: Security Alerts Table
  // =========================================================================
  async function loadAlertsTable() {
    const tbody = document.getElementById('alerts-table-body');
    const badge = document.getElementById('total-alerts-count');
    try {
      const res = await fetch('/events?limit=50');
      const events = await res.json();
      badge.textContent = `${events.length} event${events.length !== 1 ? 's' : ''}`;

      if (!events.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">No alerts logged yet.</td></tr>';
        return;
      }

      tbody.innerHTML = events.map(ev => {
        const timeStr = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleString() : '--';
        const type = ev.event_type || 'alert';
        let severityClass = 'panel-badge';
        let severityText = 'INFO';

        if (type.includes('intrusion') || type.includes('restricted')) {
          severityClass = 'badge-category restricted';
          severityText = 'CRITICAL';
        } else if (type.includes('threshold') || type.includes('capacity')) {
          severityClass = 'badge-category vip';
          severityText = 'WARNING';
        }

        const snapshotBtn = ev.snapshot_base64
          ? `<button class="btn btn-xs btn-outline" onclick="showSnapshotModal('data:image/jpeg;base64,${ev.snapshot_base64}', '${escapeHtml(type)}')">View</button>`
          : '<span class="text-subtle">None</span>';

        return `
          <tr>
            <td>${escapeHtml(timeStr)}</td>
            <td><strong>${escapeHtml(type)}</strong></td>
            <td><span class="${severityClass}">${severityText}</span></td>
            <td>${escapeHtml(ev.zone_id || ev.camera_id || 'System')}</td>
            <td>${escapeHtml(ev.entity_name || (ev.entity_id ? '#' + ev.entity_id : 'Unknown'))}</td>
            <td>${escapeHtml(JSON.stringify(ev.metadata || {}))}</td>
            <td>${snapshotBtn}</td>
          </tr>
        `;
      }).join('');
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center">Error loading events: ${err.message}</td></tr>`;
    }
  }

  // =========================================================================
  // Utilities
  // =========================================================================
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Initialize
  initWebSocket();
  window.addEventListener('resize', syncCanvasSize);

  // Global interface for multi-camera orchestration
  window.App = {
    switchCamera: switchCamera,
    getActiveCameraId: () => activeCameraId,
  };
});
