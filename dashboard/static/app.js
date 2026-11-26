/**
 * Intelligent Tracker Web Dashboard - Main Coordinator & Hash Router.
 * Coordinates LivePlayer, InteractiveCanvas, TelemetryGateway, GalleryTimeline, and AnalyticsView.
 */

document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  // Application State
  const state = {
    activeTab: 'tab-live',
    tracks: [],
    zones: [],
    tripwires: [],
    heatmap: null,
    sourceRes: null,
    hoveredTrack: null,
  };

  let activeCameraId = (() => { try { return window.localStorage?.getItem('it_focused_camera_id') || null; } catch (_) { return null; } })();
  let pendingLiveWsCamId = null;
  let activeLiveWsCamId = null;
  const videoImg = document.getElementById('live-stream-img');
  const canvas = document.getElementById('interactive-canvas');
  const ctx = canvas?.getContext('2d');
  const connStatusPill = document.getElementById('connection-status-pill');
  const connStatusText = document.getElementById('connection-status-text');
  const alertBadge = document.getElementById('header-alert-badge');

  function showToast(...args) {
    return window.AppUIHelpers?.showToast?.(...args);
  }
  window.showToast = window.showToast || showToast;

  function detachLiveStream() {
    window.LivePlayer?.detachLiveStream(videoImg);
  }

  function attachLiveStream(forceReconnect = false) {
    if (activeCameraId) window.LivePlayer?.attachLiveStream(videoImg, activeCameraId, forceReconnect);
  }

  // Tab Navigation & Hash Routing
  const navTabs = document.querySelectorAll('.nav-tab');
  const drawerTabs = document.querySelectorAll('.drawer-tab');
  const tabPanes = document.querySelectorAll('.tab-pane');

  function switchTab(targetTabId, updateHash = true) {
    const previousTab = state.activeTab;
    state.activeTab = targetTabId;

    navTabs.forEach(tab => {
      const isTarget = tab.getAttribute('data-tab') === targetTabId;
      tab.classList.toggle('active', isTarget);
      if (isTarget && tab.offsetParent !== null) {
        const wrapper = document.getElementById('nav-tabs-wrapper');
        if (wrapper && wrapper.scrollWidth > wrapper.clientWidth) {
          const wrapRect = wrapper.getBoundingClientRect();
          const tabRect = tab.getBoundingClientRect();
          const targetLeft = (tabRect.left - wrapRect.left) + wrapper.scrollLeft - (wrapper.clientWidth - tabRect.width) / 2;
          wrapper.scrollTo({ left: Math.max(0, targetLeft), behavior: 'smooth' });
          window.navTabsManager?.updateScrollButtons?.();
          setTimeout(() => window.navTabsManager?.updateScrollButtons?.(), 350);
        }
      }
    });

    if (window.scrollX !== 0) {
      window.scrollTo(0, window.scrollY);
    }

    drawerTabs.forEach(tab => {
      tab.classList.toggle('active', tab.getAttribute('data-tab') === targetTabId);
    });

    tabPanes.forEach(pane => {
      pane.classList.toggle('active', pane.id === targetTabId);
    });

    handleTabLifecycle(previousTab, targetTabId);

    if (updateHash) {
      const cleanHash = '#' + targetTabId.replace('tab-', '');
      if (window.location.hash !== cleanHash) history.pushState(null, '', cleanHash);
    }
  }

  window.switchTab = switchTab;

  function handleTabLifecycle(previousTab, targetTabId) {
    if (previousTab === 'tab-videos' && targetTabId !== 'tab-videos') {
      window.VideoScrubber?.onTabLeave?.();
    } else if (previousTab === 'tab-live' && targetTabId !== 'tab-live') {
      detachLiveStream();
    }

    if (targetTabId === 'tab-live') {
      if (activeCameraId && (pendingLiveWsCamId === activeCameraId || activeLiveWsCamId !== activeCameraId)) {
        activeLiveWsCamId = activeCameraId;
        pendingLiveWsCamId = null;
        window.TelemetryGateway?.initWebSocket(activeCameraId, onTelemetryReceived, onWsStatusChange);
      }
      if (!window.LivePlayer?.isPaused()) attachLiveStream(true);
    } else if (targetTabId === 'tab-videos') {
      window.VideoScrubber?.loadVideosList();
      window.VideoScrubber?.onTabEnter?.();
    } else if (targetTabId === 'tab-gallery') {
      window.GalleryTimeline?.loadGallery();
    } else if (targetTabId === 'tab-timeline') {
      window.GalleryTimeline?.loadTimelineFilters();
      window.GalleryTimeline?.loadSightings();
    } else if (targetTabId === 'tab-analytics') {
      window.AnalyticsView?.initChart();
      window.LivePlayer?.attachHeatmapImage?.(document.getElementById('static-heatmap-img'));
    } else if (targetTabId === 'tab-alerts') {
      window.AnalyticsView?.loadAlerts();
    } else if (targetTabId === 'tab-studio') {
      window.Studio?.renderBEV?.();
    } else if (targetTabId === 'tab-journey') {
      document.getElementById('journey-search-query')?.focus();
    } else if (targetTabId === 'tab-review') {
      window.ReviewAndRSAC?.loadQueue('pending');
    }
  }

  function handleHashRoute() {
    const raw = (window.location.hash || '').replace('#', '').trim().toLowerCase();
    if (!raw) return;
    const modalMap = {
      cameras: 'modal-camera-manager',
      enroll: 'modal-universal-enrollment',
      backup: 'modal-backup-manager',
      versions: 'modal-descriptor-versions',
    };
    if (modalMap[raw]) {
      if (raw === 'enroll' && window.UniversalEnrollment?.openModal) { window.UniversalEnrollment.openModal(); return; }
      if (raw === 'cameras' && window.CameraManager?.openModal) { window.CameraManager.openModal(); return; }
      const m = document.getElementById(modalMap[raw]);
      if (m) m.style.display = 'flex';
      return;
    }
    const tabId = raw.startsWith('tab-') ? raw : ('tab-' + raw);
    if (document.getElementById(tabId)) switchTab(tabId, false);
  }

  function switchCamera(camId) {
    if (!camId || camId === activeCameraId) return;
    activeCameraId = camId;
    if (state.activeTab === 'tab-live') {
      activeLiveWsCamId = camId;
      pendingLiveWsCamId = null;
      window.TelemetryGateway?.initWebSocket(camId, onTelemetryReceived, onWsStatusChange);
    } else {
      pendingLiveWsCamId = camId;
    }
  }

  function onTelemetryReceived(data) {
    window.latestTelemetry = data;
    state.tracks = data.active_tracks || [];
    state.zones = data.zones || state.zones;
    state.tripwires = data.tripwires || state.tripwires;
    if (data.heatmap !== undefined) state.heatmap = data.heatmap;
    if (Array.isArray(data.source_resolution) && data.source_resolution.length >= 2) {
      state.sourceRes = data.source_resolution;
    } else if (typeof data.resolution === 'string' && data.resolution.includes('x')) {
      const [rw, rh] = data.resolution.split('x').map(Number);
      if (rw > 0 && rh > 0) state.sourceRes = [rw, rh];
    }
    let totalCrossed = 0;
    if (data.tripwires) {
      data.tripwires.forEach(tw => { totalCrossed += (tw.in_count + tw.out_count); });
      window.AnalyticsView?.updateChart(totalCrossed);
    }
    window.TelemetryGateway?.updateKpiDisplays(data, state.tracks.length, totalCrossed);

    if (data.zones) window.TelemetryGateway?.renderZones(data.zones);
    if (data.tripwires) window.TelemetryGateway?.renderTripwires(data.tripwires);
    const unreadCount = typeof data.unread_alert_count === 'number'
      ? data.unread_alert_count
      : (Array.isArray(data.recent_alerts) ? data.recent_alerts.filter((a) => !a?.is_read).length : null);
    if (unreadCount !== null) {
      if (window.AppUIHelpers?.syncAlertBadges) {
        window.AppUIHelpers.syncAlertBadges(unreadCount);
      } else if (alertBadge) {
        alertBadge.textContent = String(unreadCount);
      }
    }
    if (data.recent_alerts) {
      window.TelemetryGateway?.renderMiniAlerts(data.recent_alerts);
      window.ReviewAndRSAC?.checkAlertEvents(data.recent_alerts);
    }

    syncCanvas();
  }

  function onWsStatusChange(isOnline) {
    if (connStatusPill) connStatusPill.className = `connection-status-pill ${isOnline ? 'online' : 'offline'}`;
    if (connStatusText) {
      const fullText = isOnline ? `Connected (${activeCameraId})` : 'Reconnecting...';
      if (window.TextTruncationManager && isOnline && activeCameraId.length > 14) {
        window.TextTruncationManager.apply(connStatusText, {
          fullText: fullText,
          mode: 'middle',
          maxLength: 24,
          preserveExt: false,
          label: 'Active Stream'
        });
      } else {
        connStatusText.textContent = fullText;
        connStatusText.title = fullText;
      }
    }
  }

  function syncCanvas() {
    window.InteractiveCanvas?.syncSize(videoImg, canvas);
    window.InteractiveCanvas?.drawOverlay(ctx, canvas, videoImg, state.tracks, state.hoveredTrack, {
      zones: state.zones,
      tripwires: state.tripwires,
      heatmap: state.heatmap,
      sourceRes: state.sourceRes,
    });
    window.RoiDrawTagger?.redrawDragOverlay?.(canvas);
  }

  function bindCanvasEvents() {
    if (!canvas) return;
    canvas.addEventListener('mousemove', (e) => {
      if (window.RoiDrawTagger?.isDragging?.(canvas)) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      state.hoveredTrack = window.InteractiveCanvas?.findHoveredTrack(mx, my, canvas, videoImg, state.tracks);
      syncCanvas();
      if (state.hoveredTrack) {
        window.InteractiveCanvas?.updateTooltip(state.hoveredTrack, canvas, videoImg);
      } else {
        const tooltip = document.getElementById('track-tooltip');
        if (tooltip) tooltip.style.display = 'none';
      }
    });

    canvas.addEventListener('mouseleave', () => {
      state.hoveredTrack = null;
      const tooltip = document.getElementById('track-tooltip');
      if (tooltip) tooltip.style.display = 'none';
      syncCanvas();
    });

    canvas.addEventListener('click', () => {
      if (state.hoveredTrack) window.InteractiveCanvas?.openTagModal(state.hoveredTrack);
    });

    document.getElementById('tooltip-tag-btn')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (state.hoveredTrack) window.InteractiveCanvas?.openTagModal(state.hoveredTrack);
    });

    document.getElementById('btn-quick-tag')?.addEventListener('click', () => {
      if (state.tracks[0]) window.InteractiveCanvas?.openTagModal?.(state.tracks[0]);
      else if (window.UniversalEnrollment?.openModal) window.UniversalEnrollment.openModal();
      else window.InteractiveCanvas?.openTagModal?.(null);
    });
  }

  // Setup Lifecycle Listeners
  navTabs.forEach(tab => tab.addEventListener('click', () => switchTab(tab.getAttribute('data-tab'))));
  window.addEventListener('hashchange', handleHashRoute);
  window.addEventListener('popstate', handleHashRoute);
  document.getElementById('view-all-alerts-link')?.addEventListener('click', () => switchTab('tab-alerts'));

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      if (state.activeTab === 'tab-videos') window.VideoScrubber?.onTabLeave?.();
      else if (state.activeTab === 'tab-live') detachLiveStream();
    } else {
      if (state.activeTab === 'tab-videos') window.VideoScrubber?.onTabEnter?.();
      else if (state.activeTab === 'tab-live' && !window.LivePlayer?.isPaused()) attachLiveStream(true);
    }
  });

  window.addEventListener('resize', syncCanvas);
  videoImg?.addEventListener('load', syncCanvas);
  if (window.ResizeObserver && videoImg) {
    const ro = new ResizeObserver(syncCanvas);
    ro.observe(videoImg);
    const wrapper = document.getElementById('video-wrapper');
    if (wrapper) ro.observe(wrapper);
  }

  const cleanupLiveResources = () => {
    detachLiveStream();
    window.TelemetryGateway?.closeWebSocket();
  };
  window.addEventListener('beforeunload', cleanupLiveResources);
  window.addEventListener('pagehide', cleanupLiveResources);

  // Initialize Modules
  window.LivePlayer?.bindHudButtons(videoImg, () => activeCameraId);
  window.InteractiveCanvas?.initTagModal(() => activeCameraId);
  bindCanvasEvents();
  window.AppUIHelpers?.bindDrawerAndBackup?.(drawerTabs, switchTab);
  window.GalleryTimeline?.bindGalleryEvents();
  window.GalleryTimeline?.bindTimelineEvents();
  window.GalleryTimeline?.initSnapshotModal();
  window.AnalyticsView?.initHeatmap();

  if (window.location.hash) handleHashRoute();
  if (state.activeTab === 'tab-live' && activeCameraId) {
    activeLiveWsCamId = activeCameraId;
    window.TelemetryGateway?.initWebSocket(activeCameraId, onTelemetryReceived, onWsStatusChange);
  }

  // Global interfaces
  window.App = {
    switchCamera: switchCamera,
    getActiveCameraId: () => activeCameraId,
  };
  window.App.switchCamera = switchCamera;
  window.showSnapshotModal = (imgUrl, title) => window.GalleryTimeline?.showSnapshotModal(imgUrl, title);
  window.loadGallery = () => window.GalleryTimeline?.loadGallery();
});
