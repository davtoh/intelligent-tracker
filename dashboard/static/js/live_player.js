/**
 * Intelligent Tracker - Live Player & HUD Stream Controller Submodule.
 * Handles MJPEG stream lifecycle, standby poster, reconnection backoff, and fullscreen modes.
 */

(function () {
  'use strict';

  const STANDBY_POSTER_SVG = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480"><rect width="100%" height="100%" fill="%230f172a"/><g transform="translate(320,240)" text-anchor="middle"><circle r="40" fill="%231e293b" stroke="%23334155" stroke-width="2"/><polygon points="-10,-18 20,0 -10,18" fill="%2306b6d4"/><text y="70" fill="%2394a3b8" font-family="Inter,sans-serif" font-size="14" font-weight="500">Live Stream Paused &bull; Hibernating</text><text y="92" fill="%2364748b" font-family="Inter,sans-serif" font-size="11">Click Resume Feed to reconnect camera</text></g></svg>';
  const ANNOTATION_MODE_STORAGE_KEY = 'it_live_annotated_mode';
  const LAG_THRESHOLD_MS = 120;

  let streamPaused = false;
  let streamRetryTimer = null;
  let burnedAnnotationMode = (() => {
    try { return window.localStorage?.getItem(ANNOTATION_MODE_STORAGE_KEY) === 'true'; } catch (e) { console.debug('localStorage read skipped:', e); return false; }
  })();

  function isBurnedAnnotationMode() {
    return Boolean(burnedAnnotationMode);
  }

  function syncAnnotationToggleUi() {
    const btn = document.getElementById('btn-live-annotation-mode');
    if (!btn) return;
    if (btn.dataset) btn.dataset.annotated = burnedAnnotationMode ? 'true' : 'false';
    btn.textContent = burnedAnnotationMode ? '🔥 Burned Boxes' : '🎯 Canvas Boxes';
    btn.classList?.toggle?.('active', burnedAnnotationMode);
  }

  function setBurnedAnnotationMode(enabled, videoImg, activeCameraId) {
    burnedAnnotationMode = Boolean(enabled);
    try { window.localStorage?.setItem(ANNOTATION_MODE_STORAGE_KEY, burnedAnnotationMode ? 'true' : 'false'); } catch (e) { console.debug('localStorage write skipped:', e); }
    syncAnnotationToggleUi();
    const targetImg = videoImg || document.getElementById('live-stream-img');
    const resolvedCam = activeCameraId || window.App?.getActiveCameraId?.() || null;
    if (targetImg && !streamPaused) attachLiveStream(targetImg, resolvedCam, true);
    window.dispatchEvent?.(new Event('resize'));
  }

  function updateInferenceLagHud(telemetryData = {}) {
    const hud = document.getElementById('stream-telemetry-hud');
    const lagBadge = document.getElementById('stream-lag-badge');
    const camLabel = String(telemetryData.camera_id || window.App?.getActiveCameraId?.() || 'CAM').toUpperCase();
    const resStr = telemetryData.resolution || '640x480';
    const fpsStr = typeof telemetryData.fps === 'number' ? telemetryData.fps.toFixed(1) : '0.0';
    if (hud) hud.textContent = `${camLabel} • ${resStr} • ${fpsStr} FPS`;
    window.SchedulerHUD?.updateCamera?.(telemetryData);
    if (!lagBadge) return;
    const lagMs = Number(telemetryData.inference_lag_ms || 0);
    const frameSeq = Number(telemetryData.frame_seq ?? telemetryData.frame_count ?? 0);
    const infSeq = Number(telemetryData.inference_frame_seq ?? frameSeq);
    if (!burnedAnnotationMode && lagMs >= LAG_THRESHOLD_MS) {
      lagBadge.hidden = false;
      lagBadge.textContent = `AI Lag: ${Math.round(lagMs)}ms`;
      lagBadge.dataset.seqDelta = String(Math.max(0, frameSeq - infSeq));
    } else {
      lagBadge.hidden = true;
      lagBadge.textContent = '';
    }
  }

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

  function detachGridStreams(options = {}) {
    const grid = document.getElementById('multi-grid-container');
    if (grid && typeof grid.querySelectorAll === 'function') {
      grid.querySelectorAll('img').forEach(img => {
        if (img.src && !img.src.startsWith('data:image/svg+xml')) {
          if (img.dataset) img.dataset.activeStreamSrc = img.src.split('?')[0];
        }
        window.MjpegReconnect?.detach?.(img);
        img.src = STANDBY_POSTER_SVG;
      });
    }
    if (!options?.keepWsSubscription) {
      window.MultiviewWsClient?.unsubscribeAll?.();
    }
  }

  function attachGridStreams() {
    if (window.CameraGrid?.resubscribeActiveGrid?.()) return;
    const grid = document.getElementById('multi-grid-container');
    if (!grid || typeof grid.querySelectorAll !== 'function') return;
    grid.querySelectorAll('img').forEach(img => {
      const base = img.dataset?.activeStreamSrc || (img.src && !img.src.startsWith('data:image/svg+xml') ? img.src.split('?')[0] : '');
      if (!base) return;
      img.src = `${base}?annotated=true&t=${Date.now()}`;
      window.MjpegReconnect?.attach?.(img);
    });
  }

  function detachLiveStream(videoImg, options = {}) {
    if (!options?.keepGrid) detachGridStreams();
    if (!videoImg) return;
    window.MjpegReconnect?.detach?.(videoImg);
    if (videoImg.src && !videoImg.src.startsWith('data:image/svg+xml')) {
      videoImg.dataset.activeStreamSrc = videoImg.src.split('?')[0];
    }
    videoImg.src = STANDBY_POSTER_SVG;
    setStreamStatus('paused');
  }

  function isSameHealthyStream(videoImg, cleanBase, annotatedParam, forceReconnect) {
    return (
      !forceReconnect
      && videoImg.src
      && videoImg.src.includes(cleanBase)
      && videoImg.src.includes(`annotated=${annotatedParam}`)
      && !videoImg.src.startsWith('data:image/svg+xml')
      && (videoImg.naturalWidth === undefined || videoImg.naturalWidth > 0)
    );
  }

  function attachLiveStream(videoImg, activeCameraId, forceReconnect = false) {
    if (streamPaused) return;
    const gridMode = window.CameraGrid?.getGridMode?.();
    if (gridMode && gridMode !== '1x1') {
      detachLiveStream(videoImg, { keepGrid: true });
      attachGridStreams();
      setStreamStatus('online');
      return;
    }
    if (!videoImg) return;
    if (streamRetryTimer) { clearTimeout(streamRetryTimer); streamRetryTimer = null; }
    const resolvedCam = activeCameraId || window.App?.getActiveCameraId?.() || null;
    const cleanBase = (resolvedCam ? `/stream/${encodeURIComponent(resolvedCam)}` : (videoImg.dataset?.activeStreamSrc || '')).split('?')[0];
    if (!cleanBase) return;
    if (videoImg.dataset) videoImg.dataset.activeStreamSrc = cleanBase;
    const liveTab = document.getElementById('tab-live');
    if (liveTab && !liveTab.classList?.contains('active')) {
      if (resolvedCam) window.ProcessingModeUI?.syncCameraFocus?.(resolvedCam);
      return;
    }
    const annotatedParam = burnedAnnotationMode ? 'true' : 'false';
    if (isSameHealthyStream(videoImg, cleanBase, annotatedParam, forceReconnect)) {
      setStreamStatus('online');
      return;
    }
    videoImg.src = `${cleanBase}?annotated=${annotatedParam}&t=${Date.now()}`;
    window.MjpegReconnect?.attach?.(videoImg);
    setStreamStatus('online');
    if (resolvedCam) window.ProcessingModeUI?.syncCameraFocus?.(resolvedCam);
  }

  function detachStudioStream(studioImg) {
    if (!studioImg) return;
    if (studioImg.src && !studioImg.src.startsWith('data:image/svg+xml')) {
      if (studioImg.dataset) studioImg.dataset.activeStreamSrc = studioImg.src.split('?')[0];
    }
    studioImg.src = STANDBY_POSTER_SVG;
  }

  function attachStudioStream(studioImg, cameraId) {
    if (!studioImg) return;
    const fallbackSrc = studioImg.dataset?.activeStreamSrc || studioImg.dataset?.src || studioImg.getAttribute?.('data-src') || '';
    const baseSrc = cameraId ? `/stream/${encodeURIComponent(cameraId)}` : fallbackSrc;
    const cleanBase = baseSrc.split('?')[0];
    if (!cleanBase) return;
    if (studioImg.dataset) studioImg.dataset.activeStreamSrc = cleanBase;
    studioImg.src = `${cleanBase}?t=${Date.now()}`;
  }

  function attachHeatmapImage(heatmapImg) {
    if (!heatmapImg) return;
    const baseSrc = heatmapImg.dataset?.src || heatmapImg.getAttribute?.('data-src') || '/analytics/heatmap';
    const cleanBase = baseSrc.split('?')[0];
    heatmapImg.src = `${cleanBase}?t=${Date.now()}`;
  }

  function syncTabStreams(previousTabId, targetTabId) {
    const liveImg = document.getElementById('live-stream-img');
    const studioImg = document.getElementById('studio-live-img');
    const heatmapImg = document.getElementById('static-heatmap-img');
    if (previousTabId === 'tab-live' && targetTabId !== 'tab-live') {
      detachLiveStream(liveImg);
    } else if (targetTabId !== 'tab-live') {
      window.MultiviewWsClient?.unsubscribeAll?.();
    }
    if (previousTabId === 'tab-studio' && targetTabId !== 'tab-studio') {
      detachStudioStream(studioImg);
    }
    if (targetTabId === 'tab-live' && !streamPaused) {
      const camId = window.App?.getActiveCameraId?.() || null;
      attachLiveStream(liveImg, camId, false);
    } else if (targetTabId === 'tab-studio') {
      const sel = document.getElementById('studio-camera-select');
      const isRecordedVideo = sel?.selectedOptions?.[0]?.parentElement?.label === 'Recorded Videos';
      if (isRecordedVideo) {
        detachStudioStream(studioImg);
      } else {
        const studioCam = sel?.value
          || studioImg?.dataset?.activeStreamSrc?.split('/stream/')[1]
          || window.App?.getActiveCameraId?.()
          || null;
        if (studioCam) attachStudioStream(studioImg, studioCam);
      }
    } else if (targetTabId === 'tab-analytics') {
      attachHeatmapImage(heatmapImg);
    }
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

  function bindPauseReconnectButtons(videoImg, getActiveCameraId) {
    const btnStreamPause = document.getElementById('btn-stream-pause-play');
    const streamPauseIcon = document.getElementById('stream-pause-icon');
    const streamPauseText = document.getElementById('stream-pause-text');
    const btnStreamReconnect = document.getElementById('btn-stream-reconnect');

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
  }

  function bindPlayerHudButtons(videoImg, getActiveCameraId) {
    const btnFullscreenToggle = document.getElementById('btn-fullscreen-toggle');
    const btnAnnotationMode = document.getElementById('btn-live-annotation-mode');
    syncAnnotationToggleUi();
    btnAnnotationMode?.addEventListener('click', () => {
      setBurnedAnnotationMode(!burnedAnnotationMode, videoImg, getActiveCameraId?.());
    });
    bindPauseReconnectButtons(videoImg, getActiveCameraId);
    btnFullscreenToggle?.addEventListener('click', () => toggleFullscreen(videoImg));

    document.addEventListener('fullscreenchange', () => {
      const isFs = !!document.fullscreenElement;
      const hudFsBtn = document.getElementById('btn-fullscreen-toggle');
      if (hudFsBtn) hudFsBtn.innerHTML = isFs ? '🗗 Exit Fullscreen' : '⛶ Fullscreen';
      setTimeout(() => window.dispatchEvent(new Event('resize')), 50);
      setTimeout(() => window.dispatchEvent(new Event('resize')), 200);
    });
  }

  window.LivePlayer = {
    STANDBY_POSTER_SVG: STANDBY_POSTER_SVG,
    detachGridStreams: detachGridStreams,
    attachGridStreams: attachGridStreams,
    detachLiveStream: detachLiveStream,
    attachLiveStream: attachLiveStream,
    detachStudioStream: detachStudioStream,
    attachStudioStream: attachStudioStream,
    attachHeatmapImage: attachHeatmapImage,
    syncTabStreams: syncTabStreams,
    setStreamStatus: setStreamStatus,
    toggleFullscreen: toggleFullscreen,
    bindHudButtons: bindPlayerHudButtons,
    isPaused: () => streamPaused,
    isBurnedAnnotationMode: isBurnedAnnotationMode,
    setBurnedAnnotationMode: setBurnedAnnotationMode,
    updateInferenceLagHud: updateInferenceLagHud,
  };
})();

