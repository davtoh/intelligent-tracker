/**
 * Intelligent Tracker - Live Player & Telemetry Controller (Tab 1).
 * Manages WebSocket telemetry, MJPEG streaming lifecycle, canvas overlays, and click-to-tag.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  const escapeHtml = window.escapeHtml || (s => s);
  const showToast = window.showToast || ((m, t) => console.log(m, t));

  const STANDBY_POSTER_SVG = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480"><rect width="640" height="480" fill="%230b0f19"/><circle cx="320" cy="240" r="48" fill="%231e293b"/><path d="M305 215 L345 240 L305 265 Z" fill="%2306b6d4"/><text x="320" y="320" font-family="sans-serif" font-size="14" fill="%2364748b" text-anchor="middle">Live Stream Paused / Standby</text></svg>';

  const state = {
    activeCameraId: 'cam_01',
    ws: null,
    wsConnected: false,
    wsReconnectTimer: null,
    streamPaused: false,
    streamRetryTimer: null,
    latestTelemetry: null,
    tracks: [],
    hoveredTrack: null,
    heatmapActive: false,
  };

  // DOM Elements
  const headerFps = document.getElementById('header-fps-val');
  const connStatusPill = document.getElementById('connection-status-pill');
  const connStatusText = document.getElementById('connection-status-text');
  const alertBadge = document.getElementById('header-alert-badge');

  const videoImg = document.getElementById('live-stream-img');
  const canvas = document.getElementById('interactive-canvas');
  const ctx = canvas ? canvas.getContext('2d') : null;
  const trackTooltip = document.getElementById('track-tooltip');
  const tooltipTitle = document.getElementById('tooltip-title');
  const tooltipBody = document.getElementById('tooltip-body');
  const tooltipTagBtn = document.getElementById('tooltip-tag-btn');
  const toggleHeatmapBtn = document.getElementById('toggle-heatmap-btn');

  const kpiActiveTracks = document.getElementById('kpi-active-tracks');
  const kpiTotalCrossed = document.getElementById('kpi-total-crossed');
  const zonesContainer = document.getElementById('zones-container');
  const tripwiresContainer = document.getElementById('tripwires-container');
  const liveAlertsFeed = document.getElementById('live-alerts-feed');

  function setStreamStatus(status) {
    const badge = document.getElementById('live-stream-status-badge');
    const badgeText = document.getElementById('live-stream-status-text');
    if (!badge || !badgeText) return;
    badge.className = `stream-status-badge ${status}`;
    if (status === 'online') {
      badgeText.textContent = 'LIVE';
    } else if (status === 'paused') {
      badgeText.textContent = 'PAUSED';
    } else if (status === 'reconnecting') {
      badgeText.textContent = 'RECONNECTING...';
    }
  }

  function detachLiveStream() {
    if (!videoImg) return;
    if (videoImg.src && !videoImg.src.startsWith('data:image/svg+xml')) {
      videoImg.dataset.activeStreamSrc = videoImg.src.split('?')[0];
    }
    videoImg.src = STANDBY_POSTER_SVG;
    setStreamStatus('paused');
  }

  function attachLiveStream(forceReconnect = false) {
    if (!videoImg || state.streamPaused) return;
    if (state.streamRetryTimer) {
      clearTimeout(state.streamRetryTimer);
      state.streamRetryTimer = null;
    }
    const baseSrc = videoImg.dataset.activeStreamSrc || `/stream/${state.activeCameraId || 'cam_01'}`;
    const cleanBase = baseSrc.split('?')[0];
    videoImg.src = `${cleanBase}?t=${Date.now()}`;
    setStreamStatus('online');
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      const videoCard = document.getElementById('live-video-card') || document.querySelector('.video-card');
      const target = videoCard || document.getElementById('video-wrapper') || videoImg;
      if (target) target.requestFullscreen?.().catch(err => console.error('Fullscreen request failed:', err));
    } else {
      document.exitFullscreen?.().catch(err => console.error('Exit fullscreen failed:', err));
    }
  }

  function initWebSocket(camId) {
    if (camId) state.activeCameraId = camId;
    if (state.wsReconnectTimer) {
      clearTimeout(state.wsReconnectTimer);
      state.wsReconnectTimer = null;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${encodeURIComponent(state.activeCameraId)}`;

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
      if (connStatusPill) connStatusPill.className = 'connection-status-pill online';
      if (connStatusText) connStatusText.textContent = `Connected (${state.activeCameraId})`;
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
      if (connStatusPill) connStatusPill.className = 'connection-status-pill offline';
      if (connStatusText) connStatusText.textContent = 'Reconnecting...';
      state.wsReconnectTimer = setTimeout(() => initWebSocket(state.activeCameraId), 2000);
    };

    state.ws.onerror = () => {
      state.ws?.close();
    };
  }

  function switchCamera(camId) {
    if (!camId || camId === state.activeCameraId) return;
    state.activeCameraId = camId;
    initWebSocket(camId);
    if (!state.streamPaused) {
      attachLiveStream(true);
    }
  }

  function handleTelemetry(data) {
    state.latestTelemetry = data;
    state.tracks = data.active_tracks || [];

    if (data.fps !== undefined && headerFps) {
      headerFps.textContent = data.fps.toFixed(1);
    }

    const resBadge = document.getElementById('stream-res-badge');
    if (resBadge && data.resolution) {
      resBadge.textContent = data.resolution;
    }

    if (kpiActiveTracks) {
      kpiActiveTracks.textContent = state.tracks.length;
    }

    if (data.zones && zonesContainer) {
      renderZones(data.zones);
    }

    let totalCrossed = 0;
    if (data.tripwires && tripwiresContainer) {
      renderTripwires(data.tripwires);
      data.tripwires.forEach(tw => { totalCrossed += (tw.in_count + tw.out_count); });
      if (kpiTotalCrossed) kpiTotalCrossed.textContent = totalCrossed;
      if (window.TrackerApp.Analytics?.updateChart) {
        window.TrackerApp.Analytics.updateChart(totalCrossed);
      }
    }

    if (data.recent_alerts && liveAlertsFeed) {
      renderMiniAlerts(data.recent_alerts);
      if (alertBadge) alertBadge.textContent = data.recent_alerts.length;
      if (window.ReviewAndRSAC && typeof window.ReviewAndRSAC.checkAlertEvents === 'function') {
        window.ReviewAndRSAC.checkAlertEvents(data.recent_alerts);
      }
    }

    syncCanvasSize();
    drawInteractiveOverlay();
  }

  function renderZones(zones) {
    if (!zones.length) {
      zonesContainer.innerHTML = '<div class="empty-state">No zones defined</div>';
      return;
    }
    const badge = document.getElementById('zone-count-badge');
    if (badge) badge.textContent = `${zones.length} zone${zones.length > 1 ? 's' : ''}`;
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

  function syncCanvasSize() {
    if (!videoImg || !canvas) return;
    const imgW = videoImg.clientWidth;
    const imgH = videoImg.clientHeight;
    if (!imgW || !imgH) return;

    const natW = videoImg.naturalWidth || 640;
    const natH = videoImg.naturalHeight || 480;
    const imgRatio = natW / natH;
    const elemRatio = imgW / imgH;

    let renderW, renderH, offsetX, offsetY;
    if (elemRatio > imgRatio) {
      renderH = imgH;
      renderW = renderH * imgRatio;
      offsetX = (imgW - renderW) / 2;
      offsetY = 0;
    } else {
      renderW = imgW;
      renderH = renderW / imgRatio;
      offsetX = 0;
      offsetY = (imgH - renderH) / 2;
    }

    const left = (videoImg.offsetLeft || 0) + offsetX;
    const top = (videoImg.offsetTop || 0) + offsetY;

    const pixelW = Math.round(renderW);
    const pixelH = Math.round(renderH);

    if (canvas.width !== pixelW || canvas.height !== pixelH) {
      canvas.width = pixelW;
      canvas.height = pixelH;
    }

    canvas.style.left = `${left}px`;
    canvas.style.top = `${top}px`;
    canvas.style.width = `${renderW}px`;
    canvas.style.height = `${renderH}px`;
  }

  function drawInteractiveOverlay() {
    if (!ctx || !canvas || !videoImg?.naturalWidth) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

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
        ctx.strokeStyle = '#06b6d4';
        ctx.lineWidth = 3;
        ctx.shadowColor = '#06b6d4';
        ctx.shadowBlur = 12;
        ctx.strokeRect(x, y, w, h);
        ctx.shadowBlur = 0;

        ctx.fillStyle = 'rgba(6, 182, 212, 0.12)';
        ctx.fillRect(x, y, w, h);
      }
    });
  }

  function openTagModal(track) {
    window.TrackerApp.TagModal?.open(track, state.activeCameraId);
  }

  function initLivePlayer() {
    if (videoImg) {
      videoImg.onerror = () => {
        if (!state.streamPaused) {
          setStreamStatus('reconnecting');
          if (!state.streamRetryTimer) {
            state.streamRetryTimer = setTimeout(() => {
              state.streamRetryTimer = null;
              attachLiveStream(true);
            }, 2000);
          }
        }
      };
    }

    const btnStreamPause = document.getElementById('btn-stream-pause-play');
    const streamPauseIcon = document.getElementById('stream-pause-icon');
    const streamPauseText = document.getElementById('stream-pause-text');
    const btnStreamReconnect = document.getElementById('btn-stream-reconnect');
    const btnFullscreenToggle = document.getElementById('btn-fullscreen-toggle');

    btnStreamPause?.addEventListener('click', () => {
      state.streamPaused = !state.streamPaused;
      if (state.streamPaused) {
        detachLiveStream();
        if (streamPauseIcon) streamPauseIcon.textContent = '▶️';
        if (streamPauseText) streamPauseText.textContent = 'Resume Feed';
        showToast('Stream Paused', 'Live stream paused on demand.', 'info');
      } else {
        if (streamPauseIcon) streamPauseIcon.textContent = '⏸️';
        if (streamPauseText) streamPauseText.textContent = 'Pause Feed';
        attachLiveStream(true);
        showToast('Stream Resumed', 'Live stream reconnected.', 'success');
      }
    });

    btnStreamReconnect?.addEventListener('click', () => {
      state.streamPaused = false;
      if (streamPauseIcon) streamPauseIcon.textContent = '⏸️';
      if (streamPauseText) streamPauseText.textContent = 'Pause Feed';
      attachLiveStream(true);
      showToast('Reconnecting...', 'Refreshed stream connection with server.', 'info');
    });

    btnFullscreenToggle?.addEventListener('click', toggleFullscreen);
    document.getElementById('fullscreen-btn')?.addEventListener('click', toggleFullscreen);

    document.addEventListener('fullscreenchange', () => {
      const isFs = !!document.fullscreenElement;
      const fsBtn = document.getElementById('fullscreen-btn');
      const hudFsBtn = document.getElementById('btn-fullscreen-toggle');
      if (fsBtn) fsBtn.innerHTML = isFs ? '🗗 Exit Fullscreen' : '⛶ Fullscreen';
      if (hudFsBtn) hudFsBtn.innerHTML = isFs ? '🗗 Exit Fullscreen' : '⛶ Fullscreen';
      setTimeout(syncCanvasSize, 50);
      setTimeout(syncCanvasSize, 200);
    });

    // Canvas Mouse Interaction
    if (canvas) {
      canvas.addEventListener('mousemove', (e) => {
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        if (!videoImg?.naturalWidth) return;
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

        if (found && trackTooltip) {
          const [bx, by, bw, bh] = found.bbox;
          const x = bx * scaleX;
          const y = by * scaleY;

          trackTooltip.style.display = 'block';
          const cLeft = parseFloat(canvas.style.left) || canvas.offsetLeft || 0;
          const cTop = parseFloat(canvas.style.top) || canvas.offsetTop || 0;
          trackTooltip.style.left = `${Math.min(cLeft + canvas.width - 180, Math.max(cLeft + 10, cLeft + x))}px`;
          trackTooltip.style.top = `${Math.max(cTop + 10, cTop + y - 70)}px`;

          if (tooltipTitle) tooltipTitle.textContent = found.entity_name || `Track #${found.id}`;
          if (tooltipBody) tooltipBody.textContent = `Conf: ${(found.confidence * 100).toFixed(0)}% | Dwell: ${found.dwell_time}s | State: ${found.state}`;
        } else if (trackTooltip) {
          trackTooltip.style.display = 'none';
        }
      });

      canvas.addEventListener('mouseleave', () => {
        state.hoveredTrack = null;
        if (trackTooltip) trackTooltip.style.display = 'none';
        drawInteractiveOverlay();
      });

      canvas.addEventListener('click', () => {
        if (state.hoveredTrack) openTagModal(state.hoveredTrack);
      });
    }

    tooltipTagBtn?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (state.hoveredTrack) openTagModal(state.hoveredTrack);
    });

    document.getElementById('btn-quick-tag')?.addEventListener('click', () => {
      openTagModal(state.tracks[0] || null);
    });

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

    document.getElementById('btn-snapshot-save')?.addEventListener('click', () => {
      window.open(`/stream/${state.activeCameraId || 'cam_01'}`, '_blank');
    });

    window.addEventListener('resize', syncCanvasSize);
    initWebSocket(state.activeCameraId);
    attachLiveStream();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLivePlayer);
  } else {
    initLivePlayer();
  }

  window.TrackerApp.LivePlayer = {
    attach: attachLiveStream,
    detach: detachLiveStream,
    switchCamera: switchCamera,
    toggleFullscreen: toggleFullscreen,
    openTagModal: openTagModal,
    syncCanvas: syncCanvasSize,
    getActiveCamera: () => state.activeCameraId,
  };
})();
