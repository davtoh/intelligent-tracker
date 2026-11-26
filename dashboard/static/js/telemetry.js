/**
 * Intelligent Tracker - Telemetry Stream & KPI Dashboard Submodule.
 * Handles WebSocket connection lifecycle, telemetry ingestion, and KPI card updates.
 */

(function () {
  'use strict';

  let wsReconnectTimer = null;
  let activeWs = null;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function clearReconnectTimer() {
    if (wsReconnectTimer) {
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = null;
    }
  }

  function closeWebSocket() {
    clearReconnectTimer();
    if (activeWs) {
      activeWs.onclose = null;
      activeWs.onerror = null;
      try { activeWs.close(); } catch (err) {
        console.debug('[Telemetry] WebSocket shutdown close ignored error:', err);
      }
      activeWs = null;
    }
  }

  function initWebSocket(cameraId, onMessage, onStatusChange) {
    closeWebSocket();
    if (!cameraId) return;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const rawToken = globalThis['MULTIVIEW_TOKEN'] || document.querySelector?.('meta[name="multiview-token"]')?.content || '';
    const token = rawToken ? `?token=${encodeURIComponent(rawToken)}` : '';
    const wsUrl = `${protocol}//${window.location.host}/ws/${encodeURIComponent(cameraId)}${token}`;
    try {
      activeWs = new WebSocket(wsUrl);
    } catch (e) {
      console.warn('WebSocket init error:', e);
      return;
    }
    activeWs.onopen = () => onStatusChange?.(true);
    activeWs.onmessage = (event) => {
      try { onMessage?.(JSON.parse(event.data)); } catch (err) { console.error('WS parse error:', err); }
    };
    activeWs.onclose = () => {
      onStatusChange?.(false);
      wsReconnectTimer = setTimeout(() => initWebSocket(cameraId, onMessage, onStatusChange), 2000);
    };
    activeWs.onerror = () => activeWs?.close();
  }

  function renderZones(zones) {
    const zonesContainer = document.getElementById('zones-container');
    const badge = document.getElementById('zone-count-badge');
    if (!zonesContainer) return;

    if (!zones.length) {
      zonesContainer.innerHTML = '<div class="empty-state">No zones defined</div>';
      return;
    }
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
    const tripwiresContainer = document.getElementById('tripwires-container');
    if (!tripwiresContainer) return;

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
    const liveAlertsFeed = document.getElementById('live-alerts-feed');
    if (!liveAlertsFeed) return;

    if (!alerts.length) {
      liveAlertsFeed.innerHTML = '<div class="empty-state">No active security alerts</div>';
      return;
    }
    liveAlertsFeed.innerHTML = alerts.slice(0, 5).map(a => {
      const type = a.event_type || 'alert';
      const sev = String(a.severity || '').toUpperCase();
      const isDanger = sev === 'CRITICAL' || sev === 'HIGH' || type.includes('intrusion') || type.includes('restricted') || type.includes('breach');
      const timeStr = a.timestamp ? new Date(a.timestamp * 1000).toLocaleTimeString() : '--:--';
      const subText = a.message || a.reason || a.title || a.summary || a.name || a.entity_name || a.suggested_name || a.zone_id || 'Security event';
      return `
        <div class="alert-mini-card ${isDanger ? 'intrusion' : ''}">
          <div class="alert-mini-header">
            <span>${escapeHtml(type.toUpperCase())}</span>
            <span class="alert-mini-time">${timeStr}</span>
          </div>
          <div class="alert-mini-sub">${escapeHtml(subText)}</div>
        </div>
      `;
    }).join('');
  }

  function updateKpiDisplays(data, trackCount, totalCrossed) {
    const headerFps = document.getElementById('header-fps-val');
    const drawerFps = document.getElementById('drawer-fps-val');
    const resBadge = document.getElementById('stream-res-badge');
    const kpiActiveTracks = document.getElementById('kpi-active-tracks');
    const kpiTotalCrossed = document.getElementById('kpi-total-crossed');

    if (data.fps !== undefined) {
      const fpsStr = data.fps.toFixed(1);
      if (headerFps) headerFps.textContent = fpsStr;
      if (drawerFps) drawerFps.textContent = fpsStr;
    }
    if (resBadge && data.resolution) resBadge.textContent = data.resolution;
    if (kpiActiveTracks) kpiActiveTracks.textContent = trackCount;
    if (kpiTotalCrossed) kpiTotalCrossed.textContent = totalCrossed;
    if (data.recording) {
      window.CameraRecording?.onTelemetryUpdate?.(data.recording, data.camera_id);
    }
    window.LivePlayer?.updateInferenceLagHud?.(data);
  }

  window.TelemetryGateway = {
    initWebSocket: initWebSocket,
    closeWebSocket: closeWebSocket,
    renderZones: renderZones,
    renderTripwires: renderTripwires,
    renderMiniAlerts: renderMiniAlerts,
    updateKpiDisplays: updateKpiDisplays,
  };
})();

