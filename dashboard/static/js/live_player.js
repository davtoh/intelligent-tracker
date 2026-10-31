/**
 * Intelligent Tracker - Live Player & HUD Stream Controller Submodule.
 * Handles MJPEG stream lifecycle, standby poster, reconnection backoff, and fullscreen modes.
 */

(function () {
  'use strict';

  const STANDBY_POSTER_SVG = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480"><rect width="100%" height="100%" fill="%230f172a"/><g transform="translate(320,240)" text-anchor="middle"><circle r="40" fill="%231e293b" stroke="%23334155" stroke-width="2"/><polygon points="-10,-18 20,0 -10,18" fill="%2306b6d4"/><text y="70" fill="%2394a3b8" font-family="Inter,sans-serif" font-size="14" font-weight="500">Live Stream Paused &bull; Hibernating</text><text y="92" fill="%2364748b" font-family="Inter,sans-serif" font-size="11">Click Resume Feed to reconnect camera</text></g></svg>';

  let streamPaused = false;
  let streamRetryTimer = null;

  function setStreamStatus(status) {
    const badge = document.getElementById('live-stream-status-badge');
    const badgeText = document.getElementById('live-stream-status-text');
    if (!badge || !badgeText) return;

    badge.className = `status-pill ${status}`;
    if (status === 'online') {
      badgeText.textContent = 'LIVE';
    } else if (status === 'paused') {
      badgeText.textContent = 'PAUSED';
    } else if (status === 'reconnecting') {
      badgeText.textContent = 'RECONNECTING...';
    }
  }

  function detachLiveStream(videoImg) {
    if (!videoImg) return;
    if (videoImg.src && !videoImg.src.startsWith('data:image/svg+xml')) {
      videoImg.dataset.activeStreamSrc = videoImg.src.split('?')[0];
    }
    videoImg.src = STANDBY_POSTER_SVG;
    setStreamStatus('paused');
  }

  function attachLiveStream(videoImg, activeCameraId, forceReconnect = false) {
    if (!videoImg || streamPaused) return;
    if (streamRetryTimer) {
      clearTimeout(streamRetryTimer);
      streamRetryTimer = null;
    }
    const baseSrc = videoImg.dataset.activeStreamSrc || `/stream/${activeCameraId || 'cam_01'}`;
    const cleanBase = baseSrc.split('?')[0];
    videoImg.src = `${cleanBase}?t=${Date.now()}`;
    setStreamStatus('online');
  }

  function toggleFullscreen(videoImg) {
    if (!document.fullscreenElement) {
      const videoCard = document.getElementById('live-video-card') || document.querySelector('.video-card');
      const target = videoCard || document.getElementById('video-wrapper') || videoImg;
      if (target) {
        target.requestFullscreen?.().catch(err => console.error('Fullscreen request failed:', err));
      }
    } else {
      document.exitFullscreen?.().catch(err => console.error('Exit fullscreen failed:', err));
    }
  }

  function bindPlayerHudButtons(videoImg, getActiveCameraId) {
    const btnStreamPause = document.getElementById('btn-stream-pause-play');
    const streamPauseIcon = document.getElementById('stream-pause-icon');
    const streamPauseText = document.getElementById('stream-pause-text');
    const btnStreamReconnect = document.getElementById('btn-stream-reconnect');
    const btnFullscreenToggle = document.getElementById('btn-fullscreen-toggle');

    if (btnStreamPause) {
      btnStreamPause.addEventListener('click', () => {
        streamPaused = !streamPaused;
        if (streamPaused) {
          detachLiveStream(videoImg);
          if (streamPauseIcon) streamPauseIcon.textContent = '▶️';
          if (streamPauseText) streamPauseText.textContent = 'Resume Feed';
          window.showToast?.('Stream Paused', 'Live stream paused on demand.', 'info');
        } else {
          if (streamPauseIcon) streamPauseIcon.textContent = '⏸️';
          if (streamPauseText) streamPauseText.textContent = 'Pause Feed';
          attachLiveStream(videoImg, getActiveCameraId?.(), true);
          window.showToast?.('Stream Resumed', 'Live stream reconnected.', 'success');
        }
      });
    }

    if (btnStreamReconnect) {
      btnStreamReconnect.addEventListener('click', () => {
        streamPaused = false;
        if (streamPauseIcon) streamPauseIcon.textContent = '⏸️';
        if (streamPauseText) streamPauseText.textContent = 'Pause Feed';
        attachLiveStream(videoImg, getActiveCameraId?.(), true);
        window.showToast?.('Reconnecting...', 'Refreshed stream connection with server.', 'info');
      });
    }

    if (btnFullscreenToggle) {
      btnFullscreenToggle.addEventListener('click', () => toggleFullscreen(videoImg));
    }

    document.addEventListener('fullscreenchange', () => {
      const isFs = !!document.fullscreenElement;
      const fsBtn = document.getElementById('fullscreen-btn');
      const hudFsBtn = document.getElementById('btn-fullscreen-toggle');
      if (fsBtn) fsBtn.innerHTML = isFs ? '🗗 Exit Fullscreen' : '⛶ Fullscreen';
      if (hudFsBtn) hudFsBtn.innerHTML = isFs ? '🗗 Exit Fullscreen' : '⛶ Fullscreen';
      setTimeout(() => window.dispatchEvent(new Event('resize')), 50);
      setTimeout(() => window.dispatchEvent(new Event('resize')), 200);
    });
  }

  window.LivePlayer = {
    STANDBY_POSTER_SVG: STANDBY_POSTER_SVG,
    detachLiveStream: detachLiveStream,
    attachLiveStream: attachLiveStream,
    setStreamStatus: setStreamStatus,
    toggleFullscreen: toggleFullscreen,
    bindHudButtons: bindPlayerHudButtons,
    isPaused: () => streamPaused,
  };
})();

