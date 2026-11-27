/**
 * Intelligent Tracker - Multi-Camera VMS Grid Switcher Submodule.
 * Handles 1x1, 2x2, 3x3, and 4x4 matrix layouts, pagination, WS canvas surfaces,
 * and capped MJPEG fallback socket budget.
 */

(function () {
  'use strict';

  const MAX_MJPEG_TILES_PER_PAGE = 4;
  const VALID_TILE_STATUSES = new Set(['online', 'hibernating', 'reconnecting', 'error', 'disabled']);
  let currentGridMode = '1x1';
  let lastRenderArgs = { activeCameras: [], focusedCameraId: null, onFocus: null };
  const tileSurfaces = new Map();
  let renderedTransport = null;
  let lastSubscribedKey = '';
  let wsClientBound = false;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  const getGridMode = () => currentGridMode;
  const hasWsStack = () => Boolean(window.MultiviewWsClient && window.FrameSurface);
  const isDegradedMode = () => Boolean(hasWsStack() && window.MultiviewWsClient.isDegraded?.());
  const useWsTransport = () => Boolean(hasWsStack() && !isDegradedMode());
  const getEffectiveLayout = () => (currentGridMode === '1x1' ? '1x1' : (isDegradedMode() ? '2x2' : currentGridMode));

  function normalizeTileStatus(status) {
    const raw = String(status || 'offline').toLowerCase();
    return VALID_TILE_STATUSES.has(raw) ? raw : 'offline';
  }

  function destroySurfaces() {
    tileSurfaces.forEach((surface) => surface.destroy?.());
    tileSurfaces.clear();
    renderedTransport = null;
  }

  function applyTileSourceStatus(camId, status, reason) {
    const surface = tileSurfaces.get(camId);
    if (surface) {
      if (status !== 'online') surface.resetSeq();
      surface.setStatus(status, reason);
    }
    const grid = document.getElementById('multi-grid-container');
    const tiles = Array.from(grid?.querySelectorAll?.('.camera-grid-tile') || []);
    const tile = tiles.find((t) => t.getAttribute?.('data-id') === camId);
    if (status !== 'online') window.GridTileOverlay?.clearTileOverlay?.(tile);
    const badge = tile?.querySelector?.('.tile-status-badge');
    if (badge) {
      const norm = normalizeTileStatus(status);
      badge.className = `tile-status-badge ${norm}`;
      badge.textContent = norm.toUpperCase();
    }
  }

  function bindMultiviewClient() {
    if (wsClientBound || !hasWsStack()) return;
    wsClientBound = true;
    const client = window.MultiviewWsClient;
    client.onFrame = (frame) => {
      tileSurfaces.get(frame.cameraId)?.pushFrame(frame.payload, frame.seq, frame.captureTsMs);
    };
    client.onSourceStatus = (camId, status, reason) => applyTileSourceStatus(camId, status, reason);
    client.onTelemetry = (msg) => {
      window.GridTileOverlay?.handleTelemetry?.(msg, document.getElementById('multi-grid-container'));
    };
    client.onTransportChange = () => {
      if (currentGridMode !== '1x1') {
        renderGrid(lastRenderArgs.activeCameras, lastRenderArgs.focusedCameraId, lastRenderArgs.onFocus);
      }
    };
  }

  function setGridMode(mode, activeCameras, focusedCameraId, onFocus) {
    currentGridMode = mode;
    const cameras = (activeCameras || []).map((c) => (
      mode !== '1x1' && c?.status === 'hibernating' ? { ...c, status: 'online' } : c
    ));
    window.GridPagination?.setLayout?.(getEffectiveLayout(), cameras.length);

    document.querySelectorAll('.grid-switch-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-grid') === mode);
    });

    renderGrid(cameras, focusedCameraId, onFocus);
    if (mode !== '1x1' && (activeCameras || []).some((c) => c?.status === 'hibernating')) {
      window.CameraManager?.refreshCameras?.();
    }
  }

  function buildGridTileHtml(cam, focusedCameraId, index, useWs) {
    const statusClass = normalizeTileStatus(cam.status);
    if (window.GridTileOverlay?.buildGridTileHtml) {
      return window.GridTileOverlay.buildGridTileHtml(cam, focusedCameraId, index, useWs, statusClass, MAX_MJPEG_TILES_PER_PAGE);
    }
    const idAttr = escapeHtml(cam.id);
    const media = useWs
      ? `<canvas class="tile-canvas" data-camera-id="${idAttr}"></canvas>`
      : (index < MAX_MJPEG_TILES_PER_PAGE ? `<img src="/stream/${encodeURIComponent(cam.id)}?annotated=true" />` : '<div class="tile-standby-poster"></div>');
    return `<div class="camera-grid-tile ${cam.id === focusedCameraId ? 'focused-tile' : ''}" data-id="${idAttr}"><div class="tile-video-container">${media}</div></div>`;
  }

  function bindGridTileEvents(multiGridContainer, onFocus) {
    multiGridContainer.querySelectorAll('.btn-tile-arm').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const camId = btn.getAttribute('data-camera-id');
        if (camId) window.GridTileOverlay?.toggleCameraArmed?.(camId, btn, lastRenderArgs.activeCameras);
      });
    });
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

  function mountCanvasSurfaces(multiGridContainer, cameras) {
    destroySurfaces();
    const canvases = Array.from(multiGridContainer.querySelectorAll?.('canvas.tile-canvas') || []);
    canvases.forEach((canvas) => {
      const camId = canvas.getAttribute?.('data-camera-id') || '';
      const cam = (cameras || []).find((c) => c.id === camId);
      const surface = new window.FrameSurface(canvas, {
        cameraId: camId,
        initialStatus: cam?.status || 'connecting',
      });
      tileSurfaces.set(camId, surface);
    });
  }

  function syncExistingTiles(multiGridContainer, cameras, focusedCameraId, desiredTransport) {
    if (renderedTransport !== null && renderedTransport !== desiredTransport) return false;
    const tiles = Array.from(multiGridContainer.querySelectorAll('.camera-grid-tile') || []);
    if (tiles.length !== cameras.length || tiles.length === 0) return false;
    if (renderedTransport === null) {
      const domTransport = tiles[0].querySelector?.('canvas.tile-canvas') ? 'ws' : 'mjpeg';
      if (domTransport !== desiredTransport) return false;
    }
    for (let i = 0; i < cameras.length; i += 1) {
      if (tiles[i].getAttribute?.('data-id') !== cameras[i].id) return false;
    }
    renderedTransport = desiredTransport;
    tiles.forEach((tile, i) => {
      const cam = cameras[i];
      const statusClass = normalizeTileStatus(cam.status);
      if (window.GridTileOverlay?.syncTileMeta) {
        window.GridTileOverlay.syncTileMeta(tile, cam, focusedCameraId, statusClass);
      } else {
        tile.classList?.toggle?.('focused-tile', cam.id === focusedCameraId);
      }
    });
    return true;
  }

  function getPageSlice(cameras, layoutOverride) {
    const layout = layoutOverride || currentGridMode;
    if (window.GridPagination && typeof window.GridPagination.paginate === 'function') {
      return window.GridPagination.paginate(cameras, layout);
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

  function updateDegradedBadge() {
    const badge = document.getElementById('grid-degraded-badge');
    if (badge) badge.hidden = !(currentGridMode !== '1x1' && isDegradedMode());
  }

  function bindPageNavButton(id, stepFn) {
    const btn = document.getElementById(id);
    if (!btn || btn.dataset?.bound) return;
    if (btn.dataset) btn.dataset.bound = '1';
    btn.addEventListener('click', () => {
      stepFn?.(lastRenderArgs.activeCameras.length, getEffectiveLayout());
      renderGrid(lastRenderArgs.activeCameras, lastRenderArgs.focusedCameraId, lastRenderArgs.onFocus);
    });
  }

  function bindPaginationControls() {
    bindPageNavButton('btn-grid-prev', (n, l) => window.GridPagination?.prevPage?.(n, l));
    bindPageNavButton('btn-grid-next', (n, l) => window.GridPagination?.nextPage?.(n, l));
  }

  function teardownGridContainer(multiGridContainer, options = {}) {
    destroySurfaces();
    if (!options?.keepWsSubscription) lastSubscribedKey = '';
    window.LivePlayer?.detachGridStreams?.(options);
    window.MjpegReconnect?.detachAll?.(multiGridContainer);
    multiGridContainer.innerHTML = '';
  }

  function syncMultiviewSubscription(cameras) {
    if (!hasWsStack()) return;
    const layout = getEffectiveLayout();
    const ids = getPageSlice(cameras, layout).items.map((c) => c.id).filter(Boolean);
    if (ids.length === 0) {
      lastSubscribedKey = '';
      window.MultiviewWsClient.unsubscribeAll();
      return;
    }
    const key = `${layout}:${ids.join(',')}`;
    const st = window.MultiviewWsClient.getState?.();
    if (key !== lastSubscribedKey || (!st?.connected && !st?.degraded)) {
      lastSubscribedKey = key;
      window.MultiviewWsClient.subscribe(ids, layout);
    }
  }

  function resubscribeActiveGrid() {
    if (currentGridMode === '1x1' || !useWsTransport()) return false;
    const layout = getEffectiveLayout();
    const ids = getPageSlice(lastRenderArgs.activeCameras || [], layout).items
      .map((c) => c.id)
      .filter(Boolean);
    lastSubscribedKey = ids.length ? `${layout}:${ids.join(',')}` : '';
    if (ids.length === 0) window.MultiviewWsClient.unsubscribeAll();
    else window.MultiviewWsClient.subscribe(ids, layout);
    return true;
  }

  function renderMultiGridView(multiGridContainer, singleVideoWrapper, cameras, focusedCameraId, onFocus) {
    window.LivePlayer?.detachLiveStream?.(document.getElementById('live-stream-img'), { keepGrid: true });
    singleVideoWrapper.style.display = 'none';
    const effectiveLayout = getEffectiveLayout();
    const useWs = useWsTransport();
    const desiredTransport = useWs ? 'ws' : 'mjpeg';
    multiGridContainer.style.display = 'grid';
    multiGridContainer.className = `multi-camera-grid grid-${effectiveLayout}`;
    const pageInfo = getPageSlice(cameras, effectiveLayout);
    updatePaginationBar(pageInfo);
    updateDegradedBadge();
    if (!syncExistingTiles(multiGridContainer, pageInfo.items, focusedCameraId, desiredTransport)) {
      teardownGridContainer(multiGridContainer, { keepWsSubscription: hasWsStack() });
      multiGridContainer.innerHTML = pageInfo.items
        .map((c, idx) => buildGridTileHtml(c, focusedCameraId, idx, useWs))
        .join('');
      bindGridTileEvents(multiGridContainer, onFocus);
      const liveTab = document.getElementById('tab-live');
      const isLiveActive = !liveTab || Boolean(liveTab.classList?.contains('active'));
      if (useWs) mountCanvasSurfaces(multiGridContainer, pageInfo.items);
      else if (isLiveActive) {
        multiGridContainer.querySelectorAll('img').forEach((img) => {
          img.addEventListener?.('load', () => {
            const badge = img.closest?.('.camera-grid-tile')?.querySelector?.('.tile-status-badge');
            if (badge) { badge.className = 'tile-status-badge online'; badge.textContent = 'ONLINE'; }
          });
          window.MjpegReconnect?.attach?.(img);
        });
      }
      renderedTransport = desiredTransport;
    }
    const liveTab = document.getElementById('tab-live');
    if (!liveTab || liveTab.classList?.contains('active')) syncMultiviewSubscription(cameras);
  }

  function renderGrid(activeCameras, focusedCameraId, onFocus) {
    const multiGridContainer = document.getElementById('multi-grid-container');
    const singleVideoWrapper = document.getElementById('video-wrapper');
    if (!multiGridContainer || !singleVideoWrapper) return;
    const cameras = activeCameras || [];
    lastRenderArgs = { activeCameras: cameras, focusedCameraId, onFocus };
    bindPaginationControls();
    bindMultiviewClient();

    if (currentGridMode === '1x1') {
      teardownGridContainer(multiGridContainer);
      window.GridTileOverlay?.stopAlertsPoll?.();
      multiGridContainer.style.display = 'none';
      singleVideoWrapper.style.display = 'flex';
      updatePaginationBar({ page: 1, totalPages: 1, totalItems: 0 });
      updateDegradedBadge();
      window.LivePlayer?.attachLiveStream?.(document.getElementById('live-stream-img'), focusedCameraId);
      window.dispatchEvent(new Event('resize'));
    } else {
      renderMultiGridView(multiGridContainer, singleVideoWrapper, cameras, focusedCameraId, onFocus);
      window.GridTileOverlay?.startAlertsPoll?.();
    }
    window.CameraRecording?.hydrateFromCameraList?.(cameras);
  }

  function focusCamera(cameraId, activeCameras, onFocus) {
    const cam = (activeCameras || []).find(c => c.id === cameraId) || (activeCameras || [])[0];
    const liveStreamImg = document.getElementById('live-stream-img');
    const streamTitle = document.getElementById('video-stream-title');
    const cameraSelectDropdown = document.getElementById('active-camera-select');

    if (cam) {
      const st = normalizeTileStatus(cam.status);
      if (st === 'offline' || st === 'error' || st === 'disabled') {
        window.LivePlayer?.showOfflinePoster?.(liveStreamImg, st);
      } else if (liveStreamImg) {
        const cleanBase = `/stream/${encodeURIComponent(cam.id)}`;
        if (liveStreamImg.dataset) liveStreamImg.dataset.activeStreamSrc = cleanBase;
        liveStreamImg.src = `${cleanBase}?annotated=false`;
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
    MAX_MJPEG_TILES_PER_PAGE,
    getGridMode,
    setGridMode,
    renderGrid,
    focusCamera,
    resubscribeActiveGrid,
  };
})();
