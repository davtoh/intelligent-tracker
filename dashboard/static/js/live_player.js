/**
 * Intelligent Tracker - Live Player & HUD Stream Controller Submodule.
 * Handles MJPEG stream lifecycle, standby poster, reconnection backoff, and fullscreen modes.
 */

(function () {
  'use strict';

  const STANDBY_POSTER_SVG = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480"><rect width="100%" height="100%" fill="%230f172a"/><g transform="translate(320,240)" text-anchor="middle"><circle r="40" fill="%231e293b" stroke="%23334155" stroke-width="2"/><polygon points="-10,-18 20,0 -10,18" fill="%2306b6d4"/><text y="70" fill="%2394a3b8" font-family="Inter,sans-serif" font-size="14" font-weight="500">Live Stream Paused %E2%80%A2 Hibernating</text><text y="92" fill="%2364748b" font-family="Inter,sans-serif" font-size="11">Click Resume Feed to reconnect camera</text></g></svg>';
  const OFFLINE_POSTER_SVG = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480"><rect width="100%" height="100%" fill="%230f172a"/><g transform="translate(320,240)" text-anchor="middle"><circle r="38" fill="%231e293b" stroke="%23ef4444" stroke-width="2"/><line x1="-14" y1="-14" x2="14" y2="14" stroke="%23ef4444" stroke-width="3"/><line x1="14" y1="-14" x2="-14" y2="14" stroke="%23ef4444" stroke-width="3"/><text y="68" fill="%23f87171" font-family="Inter,sans-serif" font-size="14" font-weight="600">Camera Offline / Unavailable</text><text y="90" fill="%2364748b" font-family="Inter,sans-serif" font-size="11">Check camera source or reconnect in Cameras</text></g></svg>';
  const OFFLINE_STATUSES = new Set(['offline', 'error', 'disabled']);
  const ANNOTATION_MODE_STORAGE_KEY = 'it_live_annotated_mode';
  const LAG_SHOW_MS = 180;
  const LAG_HIDE_MS = 110;
  const LAG_CONSECUTIVE_SAMPLES = 3;
  const LAG_EMA_ALPHA = 0.35;

  let streamPaused = false;
  let streamRetryTimer = null;
  let lagEmaMs = null;
  let lagHighStreak = 0;
  let lagVisible = false;
  let lagLastCamId = null;
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

  function isThrottledCadence(telemetryData) {
    const tier = String(telemetryData.priority_tier || '').toUpperCase();
    const isReplay = Boolean(telemetryData.replay_active) || tier === 'REPLAY';
    const targetFps = typeof telemetryData.target_fps === 'number' ? telemetryData.target_fps : null;
    const isThrottledP1 = tier === 'P1' && !telemetryData.motion_active && (targetFps === null || targetFps <= 2);
    const isNonLive = tier === 'P2' || tier === 'PAUSED' || tier === 'CAPTURE_ONLY' || tier === 'IDLE';
    return burnedAnnotationMode || isReplay || isThrottledP1 || isNonLive;
  }

  function evaluateLagHysteresis(telemetryData, camLabel) {
    if (isThrottledCadence(telemetryData)) {
      lagEmaMs = null; lagHighStreak = 0; lagVisible = false;
      return { show: false, emaMs: 0 };
    }
    if (camLabel !== lagLastCamId) {
      lagLastCamId = camLabel; lagEmaMs = null; lagHighStreak = 0; lagVisible = false;
    }
    const rawLagMs = Math.max(0, Number(telemetryData.inference_lag_ms || 0));
    lagEmaMs = lagEmaMs === null ? rawLagMs : (LAG_EMA_ALPHA * rawLagMs) + ((1 - LAG_EMA_ALPHA) * lagEmaMs);
    if (!lagVisible) {
      if (lagEmaMs >= LAG_SHOW_MS) {
        lagHighStreak += 1;
        if (lagHighStreak >= LAG_CONSECUTIVE_SAMPLES) lagVisible = true;
      } else {
        lagHighStreak = 0;
      }
    } else if (lagEmaMs <= LAG_HIDE_MS) {
      lagVisible = false;
      lagHighStreak = 0;
    }
    return { show: lagVisible, emaMs: lagEmaMs };
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
    const { show, emaMs } = evaluateLagHysteresis(telemetryData, camLabel);
    const frameSeq = Number(telemetryData.frame_seq ?? telemetryData.frame_count ?? 0);
    const infSeq = Number(telemetryData.inference_frame_seq ?? frameSeq);
    if (show) {
      lagBadge.hidden = false;
      lagBadge.textContent = `AI Lag: ${Math.round(emaMs)}ms`;
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
    const labels = { online: 'LIVE', paused: 'PAUSED', offline: 'OFFLINE', reconnecting: 'RECONNECTING...' };
    if (labels[status]) badgeText.textContent = labels[status];
  }

  function showOfflinePoster(videoImg, statusLabel = 'offline') {
    if (!videoImg) return;
    window.MjpegReconnect?.detach?.(videoImg);
    videoImg.src = OFFLINE_POSTER_SVG;
    setStreamStatus(OFFLINE_STATUSES.has(String(statusLabel || '').toLowerCase()) ? 'offline' : 'paused');
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
    if (streamPaused && !forceReconnect) return;
    if (forceReconnect) streamPaused = false;
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
    const camObj = resolvedCam ? window.CameraManager?.getActiveCameras?.()?.find?.((c) => c.id === resolvedCam) : null;
    if (camObj && OFFLINE_STATUSES.has(String(camObj.status || '').toLowerCase())) {
      showOfflinePoster(videoImg, camObj.status);
      return;
    }
    const cleanBase = (resolvedCam ? `/stream/${encodeURIComponent(resolvedCam)}` : (videoImg.dataset?.activeStreamSrc || '')).split('?')[0];
    if (!cleanBase) return;
    if (videoImg.dataset) videoImg.dataset.activeStreamSrc = cleanBase;
    const liveTab = document.getElementById('tab-live');
    if (liveTab && !liveTab.classList?.contains('active')) {
      if (resolvedCam) window.ProcessingModeUI?.syncCameraFocus?.(resolvedCam);
      return;
    }
    const annotatedParam = burnedAnnotationMode ? 'true' : 'false';
    if (isSameHealthyStream(videoImg, cleanBase, annotatedParam, forceReconnect)) { setStreamStatus('online'); return; }
    window.MediaEmptyState?.hideEmpty?.(videoImg, 'block');
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
    if (!cleanBase) {
      window.MediaEmptyState?.showEmpty?.(studioImg, 'No Active Camera Feed', 'Select an online camera or recorded video.');
      return;
    }
    if (studioImg.dataset) studioImg.dataset.activeStreamSrc = cleanBase;
    if (window.MediaEmptyState) window.MediaEmptyState.setSource(studioImg, `${cleanBase}?t=${Date.now()}`);
    else studioImg.src = `${cleanBase}?t=${Date.now()}`;
  }

  function attachHeatmapImage(heatmapImg) {
    if (!heatmapImg) return;
    const baseSrc = (heatmapImg.dataset?.src || heatmapImg.getAttribute?.('data-src') || '/analytics/heatmap').split('?')[0];
    const selSrc = window.AnalyticsView?.getSelectedSource?.();
    const camId = selSrc ? selSrc.id : (window.App?.getActiveCameraId?.() || '');
    const url = camId ? `${baseSrc}?camera_id=${encodeURIComponent(camId)}&t=${Date.now()}` : `${baseSrc}?t=${Date.now()}`;
    if (window.MediaEmptyState) window.MediaEmptyState.setSource(heatmapImg, url);
    else heatmapImg.src = url;
    const badge = document.getElementById('heatmap-camera-badge');
    if (badge) badge.textContent = camId ? `${selSrc?.kind === 'video' ? 'Video' : 'Camera'}: ${camId}` : 'All Cameras';
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
      if (window.StudioCanvas?.attachStudioMedia) return;
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
        else window.MediaEmptyState?.showEmpty?.(studioImg, 'No Active Camera Feed', 'Select an online camera or recorded video.');
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
    STANDBY_POSTER_SVG, OFFLINE_POSTER_SVG, showOfflinePoster,
    detachGridStreams, attachGridStreams, detachLiveStream, attachLiveStream,
    detachStudioStream, attachStudioStream, attachHeatmapImage, syncTabStreams,
    setStreamStatus, toggleFullscreen, bindHudButtons: bindPlayerHudButtons,
    isPaused: () => streamPaused, isBurnedAnnotationMode, setBurnedAnnotationMode, updateInferenceLagHud,
  };
})();

