/**
 * Intelligent Tracker - Multi-Camera VMS Grid Switcher (1x1, 2x2, 3x3).
 * Manages grid layout switching, zero-load tile eviction, and camera tile focus.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  const escapeHtml = window.escapeHtml || (s => s);

  let currentGridMode = '1x1';
  let focusedCameraId = 'cam_01';

  const multiGridContainer = document.getElementById('multi-camera-grid');
  const singleVideoWrapper = document.getElementById('live-stream-viewport-wrapper') || document.getElementById('video-wrapper');
  const liveStreamImg = document.getElementById('live-stream-img');
  const streamTitle = document.getElementById('video-stream-title');
  const cameraSelectDropdown = document.getElementById('camera-select');

  function focusCamera(cameraId, activeCameras = []) {
    focusedCameraId = cameraId;
    const cam = activeCameras.find(c => c.id === cameraId) || { id: cameraId, name: cameraId };
    if (cam) {
      if (liveStreamImg) {
        liveStreamImg.src = `/stream/${cam.id}`;
      }
      if (streamTitle) {
        const fullTitle = `Camera Feed: ${(cam.name || cam.id).toUpperCase()} (${cam.id})`;
        streamTitle.textContent = fullTitle;
        streamTitle.title = fullTitle;
      }
      if (cameraSelectDropdown) {
        cameraSelectDropdown.value = cam.id;
      }
      if (window.TrackerApp.LivePlayer?.switchCamera) {
        window.TrackerApp.LivePlayer.switchCamera(cam.id);
      }
    }
    setGridMode('1x1', activeCameras);
  }

  function setGridMode(mode, activeCameras = []) {
    currentGridMode = mode;

    document.querySelectorAll('.grid-switch-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-grid') === mode);
    });

    renderGrid(activeCameras);
  }

  function renderGrid(activeCameras = []) {
    if (!multiGridContainer || !singleVideoWrapper) return;

    if (currentGridMode === '1x1') {
      multiGridContainer.style.display = 'none';
      multiGridContainer.innerHTML = ''; // Deep hardware hibernation: detach background grid streams
      singleVideoWrapper.style.display = 'flex';
      window.dispatchEvent(new Event('resize'));
    } else {
      singleVideoWrapper.style.display = 'none';
      multiGridContainer.style.display = 'grid';
      multiGridContainer.className = `multi-camera-grid grid-${currentGridMode}`;

      multiGridContainer.innerHTML = activeCameras.map(cam => `
        <div class="camera-grid-tile glass-panel ${cam.id === focusedCameraId ? 'focused-tile' : ''}" data-id="${cam.id}">
          <div class="tile-header">
            <span class="tile-title">${escapeHtml(cam.name)}</span>
            <span class="tile-status-badge ${cam.status === 'online' ? 'online' : 'offline'}">${cam.status.toUpperCase()}</span>
          </div>
          <div class="tile-video-container">
            <img src="/stream/${cam.id}" alt="${escapeHtml(cam.name)}" loading="lazy" />
          </div>
          <div class="tile-footer">
            <span class="tile-fps">${cam.fps} FPS</span>
            <span class="tile-tracks">${cam.active_tracks_count || 0} tracks</span>
            <button class="btn btn-xs btn-primary btn-tile-focus" data-id="${cam.id}">🔍 View 1x1</button>
          </div>
        </div>
      `).join('');

      multiGridContainer.querySelectorAll('.camera-grid-tile, .btn-tile-focus').forEach(elem => {
        elem.addEventListener('click', () => {
          const camId = elem.getAttribute('data-id');
          if (camId) {
            focusCamera(camId, activeCameras);
          }
        });
      });
    }
  }

  window.addEventListener('beforeunload', () => {
    if (multiGridContainer) multiGridContainer.innerHTML = '';
  });
  window.addEventListener('pagehide', () => {
    if (multiGridContainer) multiGridContainer.innerHTML = '';
  });

  window.TrackerApp.MultiGrid = {
    setGridMode: setGridMode,
    renderGrid: renderGrid,
    focusCamera: focusCamera,
    getGridMode: () => currentGridMode,
  };
})();

