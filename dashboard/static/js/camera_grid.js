/**
 * Intelligent Tracker - Multi-Camera VMS Grid Switcher Submodule.
 * Handles 1x1, 2x2, and 3x3 matrix layouts, stream tile rendering, and camera focus.
 */

(function () {
  'use strict';

  let currentGridMode = '1x1';

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

    document.querySelectorAll('.grid-switch-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-grid') === mode);
    });

    renderGrid(activeCameras, focusedCameraId, onFocus);
  }

  function renderGrid(activeCameras, focusedCameraId, onFocus) {
    const multiGridContainer = document.getElementById('multi-grid-container');
    const singleVideoWrapper = document.getElementById('video-wrapper');
    if (!multiGridContainer || !singleVideoWrapper) return;

    if (currentGridMode === '1x1') {
      multiGridContainer.style.display = 'none';
      multiGridContainer.innerHTML = '';
      singleVideoWrapper.style.display = 'flex';
      window.dispatchEvent(new Event('resize'));
    } else {
      singleVideoWrapper.style.display = 'none';
      multiGridContainer.style.display = 'grid';
      multiGridContainer.className = `multi-camera-grid grid-${currentGridMode}`;

      multiGridContainer.innerHTML = (activeCameras || []).map(cam => `
        <div class="camera-grid-tile glass-panel ${cam.id === focusedCameraId ? 'focused-tile' : ''}" data-id="${escapeHtml(cam.id)}">
          <div class="tile-header">
            <span class="tile-title">${escapeHtml(cam.name)}</span>
            <span class="tile-status-badge ${cam.status === 'online' ? 'online' : 'offline'}">${escapeHtml(cam.status.toUpperCase())}</span>
          </div>
          <div class="tile-video-container">
            <img src="/stream/${encodeURIComponent(cam.id)}" alt="${escapeHtml(cam.name)}" loading="lazy" />
          </div>
          <div class="tile-footer">
            <span class="tile-fps">${cam.fps} FPS</span>
            <span class="tile-tracks">${cam.active_tracks_count || 0} tracks</span>
            <button class="btn btn-xs btn-primary btn-tile-focus" data-id="${escapeHtml(cam.id)}">🔍 View 1x1</button>
          </div>
        </div>
      `).join('');

      multiGridContainer.querySelectorAll('.camera-grid-tile, .btn-tile-focus').forEach(elem => {
        elem.addEventListener('click', () => {
          const camId = elem.getAttribute('data-id');
          if (camId && onFocus) onFocus(camId);
        });
      });
    }
  }

  function focusCamera(cameraId, activeCameras, onFocus) {
    const cam = (activeCameras || []).find(c => c.id === cameraId) || (activeCameras || [])[0];
    const liveStreamImg = document.getElementById('live-stream-img');
    const streamTitle = document.getElementById('video-stream-title');
    const cameraSelectDropdown = document.getElementById('active-camera-select');

    if (cam) {
      if (liveStreamImg) {
        liveStreamImg.src = `/stream/${cam.id}`;
      }
      if (streamTitle) {
        const fullTitle = `Camera Feed: ${cam.name.toUpperCase()} (${cam.id})`;
        streamTitle.textContent = fullTitle;
        streamTitle.title = fullTitle;
      }
      if (cameraSelectDropdown) {
        cameraSelectDropdown.value = cam.id;
      }
      if (window.App && typeof window.App.switchCamera === 'function') {
        window.App.switchCamera(cam.id);
      }
    }
    setGridMode('1x1', activeCameras, cameraId, onFocus);
  }

  window.CameraGrid = {
    getGridMode: getGridMode,
    setGridMode: setGridMode,
    renderGrid: renderGrid,
    focusCamera: focusCamera,
  };
})();

