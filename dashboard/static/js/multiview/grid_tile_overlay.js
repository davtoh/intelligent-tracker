/**
 * Intelligent Tracker - Multiview Grid Tile AI Overlay, Armed Toggle & Pool Alerts.
 * Renders per-tile client-side bounding boxes via UnifiedCanvasOverlay, updates
 * live tile FPS/track/tier/ai_active state from MultiviewWsClient.onTelemetry,
 * toggles per-camera `armed` state via PATCH /api/cameras/{id}, and polls
 * pool-wide Recent Alerts when viewing multiview grids.
 */
(function () {
  'use strict';

  let alertsPollTimer = null;
  let alertsPollInFlight = false;
  const lastTelemetryByTile = new WeakMap();
  const lastSeqByTile = new WeakMap();
  const tileResizeObservers = new WeakMap();

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function buildTileMediaHtml(cam, index, useWs, maxMjpegTiles = 4) {
    const idAttr = escapeHtml(cam.id);
    const overlay = `<canvas class="tile-overlay-canvas" data-camera-id="${idAttr}"></canvas>`;
    if (useWs) {
      return `<canvas class="tile-canvas" data-camera-id="${idAttr}" aria-label="${escapeHtml(cam.name)} live feed"></canvas>${overlay}`;
    }
    if (index < maxMjpegTiles) {
      return `<img src="/stream/${encodeURIComponent(cam.id)}?annotated=true" alt="${escapeHtml(cam.name)}" />${overlay}`;
    }
    return `
      <div class="tile-standby-poster" data-standby-tile="true">
        <span class="tile-standby-label">Standby (${maxMjpegTiles} live/page cap)</span>
        <button type="button" class="btn btn-xs btn-primary btn-tile-view" data-id="${idAttr}">🔍 View</button>
      </div>`;
  }

  function buildGridTileHtml(cam, focusedCameraId, index, useWs, statusClass, maxMjpegTiles = 4) {
    const idAttr = escapeHtml(cam.id);
    const armed = Boolean(cam.armed);
    return `
      <div class="camera-grid-tile glass-panel ${cam.id === focusedCameraId ? 'focused-tile' : ''}" data-id="${idAttr}">
        <div class="tile-header">
          <span class="tile-title">${escapeHtml(cam.name)}</span>
          <div class="tile-header-badges">
            <span class="tile-rec-badge" data-camera-id="${idAttr}" hidden>REC</span>
            <span class="tile-status-badge ${statusClass}">${escapeHtml(statusClass.toUpperCase())}</span>
          </div>
        </div>
        <div class="tile-video-container">${buildTileMediaHtml(cam, index, useWs, maxMjpegTiles)}</div>
        <div class="tile-footer">
          <span class="tile-fps">${cam.fps ?? 0} FPS</span>
          <span class="tile-tracks">${cam.active_tracks_count || 0} tracks</span>
          <div class="tile-actions">
            <button type="button" class="btn btn-xs btn-outline btn-tile-arm ${armed ? 'active' : ''}" data-camera-id="${idAttr}" data-armed="${armed ? 'true' : 'false'}" title="Toggle Background AI (Armed)">${armed ? '🛡 AI ON' : '🛡 AI OFF'}</button>
            <button type="button" class="btn btn-xs btn-outline btn-tile-record" data-camera-id="${idAttr}" title="Start/Stop MP4 Recording">⏺ Rec</button>
            <button type="button" class="btn btn-xs btn-primary btn-tile-focus" data-id="${idAttr}">🔍 View 1x1</button>
          </div>
        </div>
      </div>`;
  }

  function findTile(gridContainer, camId) {
    if (!gridContainer || !camId) return null;
    const tiles = Array.from(gridContainer.querySelectorAll?.('.camera-grid-tile') || []);
    return tiles.find((t) => t.getAttribute?.('data-id') === camId) || null;
  }

  function clearTileOverlay(tile) {
    lastTelemetryByTile.delete(tile);
    const canvas = tile?.querySelector?.('canvas.tile-overlay-canvas');
    if (!canvas) return;
    if (canvas.style) { canvas.style.width = ''; canvas.style.height = ''; }
    const ctx = canvas.getContext?.('2d');
    if (ctx) ctx.clearRect(0, 0, canvas.width || 0, canvas.height || 0);
  }

  function ensureTileResizeObserver(tile) {
    if (!tile || tileResizeObservers.has(tile) || typeof window.ResizeObserver !== 'function') return;
    const container = tile.querySelector?.('.tile-video-container') || tile;
    const ro = new window.ResizeObserver(() => {
      const prev = lastTelemetryByTile.get(tile);
      if (prev) renderTileTracks(tile, prev);
    });
    ro.observe(container);
    tileResizeObservers.set(tile, ro);
  }

  function renderTileTracks(tile, msg) {
    const canvas = tile?.querySelector?.('canvas.tile-overlay-canvas');
    if (!canvas || !window.UnifiedCanvasOverlay) return;
    const ctx = canvas.getContext?.('2d');
    if (!ctx) return;
    const container = tile?.querySelector?.('.tile-video-container') || canvas.parentElement || canvas;
    const rect = container.getBoundingClientRect?.() || canvas.getBoundingClientRect?.() || { left: 0, top: 0, width: container.clientWidth || 320, height: container.clientHeight || 180 };
    const cssW = rect.width > 0 ? rect.width : (container.clientWidth || canvas.clientWidth || 320);
    const cssH = rect.height > 0 ? rect.height : (container.clientHeight || canvas.clientHeight || 180);
    const res = Array.isArray(msg.source_resolution) && msg.source_resolution.length >= 2 ? msg.source_resolution : [640, 480];
    window.UnifiedCanvasOverlay.syncCanvasDpr(canvas, ctx, cssW, cssH, undefined, { responsive: true });
    ensureTileResizeObserver(tile);
    lastTelemetryByTile.set(tile, msg);
    const box = window.UnifiedCanvasOverlay.computeCoverBox({ left: 0, top: 0, width: cssW, height: cssH }, null, res[0], res[1]);
    window.UnifiedCanvasOverlay.renderScene(ctx, {
      tracks: Array.isArray(msg.tracks) ? msg.tracks : [],
      transform: { offsetX: box.offsetX, offsetY: box.offsetY, scaleX: box.scale, scaleY: box.scale },
      clearWidth: cssW,
      clearHeight: cssH,
      visibility: { bboxes: true, track_ids: true, dwell_timers: false, velocity: false, zones: false, tripwires: false, heatmap: false },
    });
  }

  function applyArmedButtonUi(btn, armed, tier, aiActive) {
    if (!btn) return;
    const isArmed = Boolean(armed);
    if (btn.dataset) btn.dataset.armed = isArmed ? 'true' : 'false';
    btn.classList?.toggle?.('active', isArmed);
    btn.textContent = isArmed ? '🛡 AI ON' : '🛡 AI OFF';
    const stateLabel = aiActive ? 'active' : 'standby';
    btn.title = `Background AI ${isArmed ? 'Armed' : 'Disarmed'} (${tier || 'P2'} • ${stateLabel})`;
  }

  function handleTelemetry(msg, gridContainer) {
    if (!msg || !msg.camera_id) return;
    const tile = findTile(gridContainer || document.getElementById('multi-grid-container'), msg.camera_id);
    if (!tile) return;
    if (msg.paused || msg.stopped || (msg.status && msg.status !== 'online')) {
      clearTileOverlay(tile);
      return;
    }
    const badge = tile.querySelector?.('.tile-status-badge');
    if (badge) {
      badge.className = 'tile-status-badge online';
      badge.textContent = 'ONLINE';
    }
    if (msg.seq != null && lastSeqByTile.get(tile) === msg.seq && (!msg.tracks || !msg.tracks.length)) {
      clearTileOverlay(tile);
    }
    if (msg.seq != null) lastSeqByTile.set(tile, msg.seq);
    const fpsEl = tile.querySelector?.('.tile-fps');
    if (fpsEl) fpsEl.textContent = `${Number(msg.fps || 0).toFixed(1)} FPS`;
    const tracks = Array.isArray(msg.tracks) ? msg.tracks : [];
    const tracksEl = tile.querySelector?.('.tile-tracks');
    if (tracksEl) tracksEl.textContent = `${tracks.length} tracks`;
    const armed = msg.armed ?? msg.is_armed ?? false;
    applyArmedButtonUi(tile.querySelector?.('.btn-tile-arm'), armed, msg.priority_tier, msg.ai_active);
    renderTileTracks(tile, msg);
  }

  async function toggleCameraArmed(camId, btn, activeCameras) {
    if (!camId || !btn) return false;
    const prevArmed = btn.dataset?.armed === 'true';
    const nextArmed = !prevArmed;
    applyArmedButtonUi(btn, nextArmed, btn.dataset?.tier, nextArmed);
    try {
      const res = await fetch(`/api/cameras/${encodeURIComponent(camId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ armed: nextArmed }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const cam = (activeCameras || []).find((c) => c.id === camId);
      if (cam) cam.armed = nextArmed;
      return true;
    } catch (err) {
      applyArmedButtonUi(btn, prevArmed, btn.dataset?.tier, prevArmed);
      console.warn('[GridTileOverlay] Failed to toggle armed state:', err);
      return false;
    }
  }

  async function refreshPoolAlerts() {
    if (alertsPollInFlight) return;
    alertsPollInFlight = true;
    try {
      const res = await fetch('/events?limit=10');
      if (!res.ok) return;
      const data = await res.json();
      const alerts = Array.isArray(data) ? data : (data?.items || data?.events || data?.alerts || []);
      const unreadCount = typeof data?.unread_alert_count === 'number'
        ? data.unread_alert_count
        : alerts.filter((a) => !a?.is_read).length;
      window.TelemetryGateway?.renderMiniAlerts?.(alerts);
      window.AppUIHelpers?.syncAlertBadges?.(unreadCount);
    } catch (err) {
      console.debug('[GridTileOverlay] Pool alerts poll skipped:', err);
    } finally {
      alertsPollInFlight = false;
    }
  }

  function startAlertsPoll(intervalMs = 4000) {
    if (!alertsPollTimer) {
      refreshPoolAlerts();
      alertsPollTimer = setInterval(() => refreshPoolAlerts(), intervalMs);
    }
  }

  function stopAlertsPoll() {
    if (alertsPollTimer) {
      clearInterval(alertsPollTimer);
      alertsPollTimer = null;
    }
  }

  function syncTileMeta(tile, cam, focusedCameraId, statusClass) {
    tile.classList?.toggle?.('focused-tile', cam.id === focusedCameraId);
    if (statusClass !== 'online') clearTileOverlay(tile);
    const badge = tile.querySelector?.('.tile-status-badge');
    if (badge) { badge.className = `tile-status-badge ${statusClass}`; badge.textContent = statusClass.toUpperCase(); }
    const fpsEl = tile.querySelector?.('.tile-fps');
    if (fpsEl) fpsEl.textContent = `${cam.fps ?? 0} FPS`;
    const tracksEl = tile.querySelector?.('.tile-tracks');
    if (tracksEl) tracksEl.textContent = `${cam.active_tracks_count || 0} tracks`;
    applyArmedButtonUi(tile.querySelector?.('.btn-tile-arm'), cam.armed, cam.priority_tier, cam.ai_active);
  }

  window.GridTileOverlay = {
    buildTileMediaHtml,
    buildGridTileHtml,
    handleTelemetry,
    renderTileTracks,
    clearTileOverlay,
    applyArmedButtonUi,
    syncTileMeta,
    toggleCameraArmed,
    refreshPoolAlerts,
    startAlertsPoll,
    stopAlertsPoll,
  };
})();
