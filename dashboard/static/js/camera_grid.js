/**
 * Intelligent Tracker - Multi-Camera VMS Grid Switcher Submodule.
 * Handles 1x1, 2x2, 3x3, and 4x4 matrix layouts, pagination, and MJPEG socket budget.
 */

(function () {
  'use strict';

  const MAX_MJPEG_TILES_PER_PAGE = 4;
  let currentGridMode = '1x1';
  let lastRenderArgs = { activeCameras: [], focusedCameraId: null, onFocus: null };

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function getGridMode() {
    return currentGridMode;
  }

  function setGridMode(mode, activeCameras, focusedCameraId, onFocus) {
    currentGridMode = mode;
    window.GridPagination?.setLayout?.(mode, (activeCameras || []).length);

    document.querySelectorAll('.grid-switch-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-grid') === mode);
    });

    renderGrid(activeCameras, focusedCameraId, onFocus);
  }

  function buildTileMediaHtml(cam, index) {
    const idAttr = escapeHtml(cam.id);
    if (index < MAX_MJPEG_TILES_PER_PAGE) {
      return `<img src="/stream/${encodeURIComponent(cam.id)}?annotated=true" alt="${escapeHtml(cam.name)}" />`;
    }
    return `
      <div class="tile-standby-poster" data-standby-tile="true">
        <span class="tile-standby-label">Standby (4 live/page cap)</span>
        <button type="button" class="btn btn-xs btn-primary btn-tile-view" data-id="${idAttr}">🔍 View</button>
      </div>
    `;
  }

  function buildGridTileHtml(cam, focusedCameraId, index) {
    const idAttr = escapeHtml(cam.id);
    const statusText = String(cam.status || 'offline');
    const statusClass = statusText === 'online' ? 'online' : 'offline';
    return `
      <div class="camera-grid-tile glass-panel ${cam.id === focusedCameraId ? 'focused-tile' : ''}" data-id="${idAttr}">
        <div class="tile-header">
          <span class="tile-title">${escapeHtml(cam.name)}</span>
          <div class="tile-header-badges">
            <span class="tile-rec-badge" data-camera-id="${idAttr}" hidden>REC</span>
            <span class="tile-status-badge ${statusClass}">${escapeHtml(statusText.toUpperCase())}</span>
          </div>
        </div>
        <div class="tile-video-container">${buildTileMediaHtml(cam, index)}</div>
        <div class="tile-footer">
          <span class="tile-fps">${cam.fps ?? 0} FPS</span>
          <span class="tile-tracks">${cam.active_tracks_count || 0} tracks</span>
          <div class="tile-actions">
            <button type="button" class="btn btn-xs btn-outline btn-tile-record" data-camera-id="${idAttr}" title="Start/Stop MP4 Recording">⏺ Rec</button>
            <button type="button" class="btn btn-xs btn-primary btn-tile-focus" data-id="${idAttr}">🔍 View 1x1</button>
          </div>
        </div>
      </div>
    `;
  }

  function bindGridTileEvents(multiGridContainer, onFocus) {
    multiGridContainer.querySelectorAll('.btn-tile-record').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const camId = btn.getAttribute('data-camera-id');
        if (camId) window.CameraRecording?.toggleCameraRecording?.(camId);
      });
    });
    multiGridContainer.querySelectorAll('.camera-grid-tile, .btn-tile-focus, .btn-tile-view').forEach(elem => {
      elem.addEventListener('click', (e) => {
        e.stopPropagation();
        const camId = elem.getAttribute('data-id');
        if (camId && onFocus) onFocus(camId);
      });
    });
  }

  function syncExistingTiles(multiGridContainer, cameras, focusedCameraId) {
    const tiles = Array.from(multiGridContainer.querySelectorAll('.camera-grid-tile') || []);
    if (tiles.length !== cameras.length || tiles.length === 0) return false;
    for (let i = 0; i < cameras.length; i += 1) {
      if (tiles[i].getAttribute?.('data-id') !== cameras[i].id) return false;
    }
    tiles.forEach((tile, i) => {
      const cam = cameras[i];
      const statusText = String(cam.status || 'offline');
      tile.classList?.toggle?.('focused-tile', cam.id === focusedCameraId);
      const badge = tile.querySelector?.('.tile-status-badge');
      if (badge) {
        badge.className = `tile-status-badge ${statusText === 'online' ? 'online' : 'offline'}`;
        badge.textContent = statusText.toUpperCase();
      }
      const fpsEl = tile.querySelector?.('.tile-fps');
      if (fpsEl) fpsEl.textContent = `${cam.fps ?? 0} FPS`;
      const tracksEl = tile.querySelector?.('.tile-tracks');
      if (tracksEl) tracksEl.textContent = `${cam.active_tracks_count || 0} tracks`;
    });
    return true;
  }

  function getPageSlice(cameras) {
    if (window.GridPagination && typeof window.GridPagination.paginate === 'function') {
      return window.GridPagination.paginate(cameras, currentGridMode);
    }
    return { items: cameras, page: 1, totalPages: 1, pageSize: cameras.length || 1, totalItems: cameras.length };
  }

  function updatePaginationBar(pageInfo) {
    const bar = document.getElementById('grid-pagination-bar');
    if (!bar) return;
    const show = currentGridMode !== '1x1' && pageInfo.totalItems > 0;
    bar.hidden = !show;
    if (!show) return;
    const indicator = document.getElementById('grid-page-indicator');
    const prevBtn = document.getElementById('btn-grid-prev');
    const nextBtn = document.getElementById('btn-grid-next');
    if (indicator) indicator.textContent = `Page ${pageInfo.page} of ${pageInfo.totalPages}`;
    if (prevBtn) prevBtn.disabled = pageInfo.page <= 1;
    if (nextBtn) nextBtn.disabled = pageInfo.page >= pageInfo.totalPages;
  }

  function bindPaginationControls() {
    const prevBtn = document.getElementById('btn-grid-prev');
    const nextBtn = document.getElementById('btn-grid-next');
    if (prevBtn && !prevBtn.dataset?.bound) {
      if (prevBtn.dataset) prevBtn.dataset.bound = '1';
      prevBtn.addEventListener('click', () => {
        window.GridPagination?.prevPage?.(lastRenderArgs.activeCameras.length, currentGridMode);
        renderGrid(lastRenderArgs.activeCameras, lastRenderArgs.focusedCameraId, lastRenderArgs.onFocus);
      });
    }
    if (nextBtn && !nextBtn.dataset?.bound) {
      if (nextBtn.dataset) nextBtn.dataset.bound = '1';
      nextBtn.addEventListener('click', () => {
        window.GridPagination?.nextPage?.(lastRenderArgs.activeCameras.length, currentGridMode);
        renderGrid(lastRenderArgs.activeCameras, lastRenderArgs.focusedCameraId, lastRenderArgs.onFocus);
      });
    }
  }

  function teardownGridContainer(multiGridContainer) {
    window.LivePlayer?.detachGridStreams?.();
    window.MjpegReconnect?.detachAll?.(multiGridContainer);
    multiGridContainer.innerHTML = '';
  }

  function renderGrid(activeCameras, focusedCameraId, onFocus) {
    const multiGridContainer = document.getElementById('multi-grid-container');
    const singleVideoWrapper = document.getElementById('video-wrapper');
    if (!multiGridContainer || !singleVideoWrapper) return;
    const cameras = activeCameras || [];
    lastRenderArgs = { activeCameras: cameras, focusedCameraId, onFocus };
    bindPaginationControls();

    if (currentGridMode === '1x1') {
      teardownGridContainer(multiGridContainer);
      multiGridContainer.style.display = 'none';
      singleVideoWrapper.style.display = 'flex';
      updatePaginationBar({ page: 1, totalPages: 1, totalItems: 0 });
      window.LivePlayer?.attachLiveStream?.(document.getElementById('live-stream-img'), focusedCameraId);
      window.dispatchEvent(new Event('resize'));
    } else {
      window.LivePlayer?.detachLiveStream?.(document.getElementById('live-stream-img'));
      singleVideoWrapper.style.display = 'none';
      multiGridContainer.style.display = 'grid';
      multiGridContainer.className = `multi-camera-grid grid-${currentGridMode}`;
      const pageInfo = getPageSlice(cameras);
      updatePaginationBar(pageInfo);
      if (!syncExistingTiles(multiGridContainer, pageInfo.items, focusedCameraId)) {
        teardownGridContainer(multiGridContainer);
        multiGridContainer.innerHTML = pageInfo.items
          .map((c, idx) => buildGridTileHtml(c, focusedCameraId, idx))
          .join('');
        bindGridTileEvents(multiGridContainer, onFocus);
        multiGridContainer.querySelectorAll('img').forEach(img => window.MjpegReconnect?.attach?.(img));
      }
    }
    window.CameraRecording?.hydrateFromCameraList?.(cameras);
  }

  function focusCamera(cameraId, activeCameras, onFocus) {
    const cam = (activeCameras || []).find(c => c.id === cameraId) || (activeCameras || [])[0];
    const liveStreamImg = document.getElementById('live-stream-img');
    const streamTitle = document.getElementById('video-stream-title');
    const cameraSelectDropdown = document.getElementById('active-camera-select');

    if (cam) {
      if (liveStreamImg) {
        liveStreamImg.src = `/stream/${encodeURIComponent(cam.id)}?annotated=false`;
      }
      if (streamTitle) {
        const fullTitle = `Camera Feed: ${cam.name.toUpperCase()} (${cam.id})`;
        streamTitle.textContent = fullTitle;
        streamTitle.title = fullTitle;
      }
      if (cameraSelectDropdown) cameraSelectDropdown.value = cam.id;
      if (window.App && typeof window.App.switchCamera === 'function') window.App.switchCamera(cam.id);
      window.CameraRecording?.onCameraFocused?.(cam.id);
    }
    setGridMode('1x1', activeCameras, cameraId, onFocus);
  }

  window.CameraGrid = {
    MAX_MJPEG_TILES_PER_PAGE: MAX_MJPEG_TILES_PER_PAGE,
    getGridMode: getGridMode,
    setGridMode: setGridMode,
    renderGrid: renderGrid,
    focusCamera: focusCamera,
  };
})();
